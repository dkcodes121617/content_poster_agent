-- ═══════════════════════════════════════════════════════════════════════════
-- Content Poster 004 — the trend intelligence layer (TRENDS.md)
-- ═══════════════════════════════════════════════════════════════════════════
-- Three tables, one per stage, because each has a different lifetime:
--
--   trend_items    raw and cheap, high volume, expires in days
--   trend_sources  captured evidence, must outlive the post that cited it
--   trend_angles   the usable output, expires the moment it goes stale
--
-- WRITER NOTE — this is the one place two agents touch one schema.
--   trend_items    <- Lead Finder (piggyback) AND the trends harvester
--   trend_sources  <- Content Poster only
--   trend_angles   <- Content Poster only
--
-- The Lead Finder already fetches HN, Reddit, X and Stack Exchange every 30
-- minutes and discards everything that is not a lead. Writing those same
-- payloads here costs one INSERT and zero API calls. It writes only to
-- trend_items, only append-only, and never reads back — so there is still
-- exactly one dedup authority per table and no cycle between agents.
-- ═══════════════════════════════════════════════════════════════════════════

-- ───────────────────────────────────────────────────────────────────────────
-- trend_items — raw candidates. High volume, low value each.
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS content.trend_items (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source        text NOT NULL,        -- hackernews | github | rss | reddit | ...
    external_id   text NOT NULL,        -- stable within the source
    title         text NOT NULL,
    url           text,
    summary       text,
    author        text,
    -- Whatever the source uses to say "this is hot": points, stars, comments.
    -- Kept raw and un-normalised; comparing a HN point to a GitHub star is
    -- meaningless, so velocity is computed per source in Python.
    signals       jsonb NOT NULL DEFAULT '{}'::jsonb,
    published_at  timestamptz,
    surfaced_at   timestamptz NOT NULL DEFAULT now(),

    -- Set once the item has been clustered with others telling the same story.
    -- The same launch appears on HN, Reddit and three newsletters; without a
    -- cluster it would be scored (and posted) five times.
    cluster_key   text,

    -- new -> scored -> verified -> angled | rejected | expired
    status        text NOT NULL DEFAULT 'new'
                  CHECK (status IN ('new','scored','verified','angled','rejected','expired')),
    relevance     int CHECK (relevance BETWEEN 0 AND 100),
    reject_reason text,
    raw           jsonb NOT NULL DEFAULT '{}'::jsonb,

    CONSTRAINT trend_items_uniq UNIQUE (source, external_id)
);

-- The scoring query: newest unscored first.
CREATE INDEX IF NOT EXISTS trend_items_new_idx
    ON content.trend_items (surfaced_at DESC) WHERE status = 'new';
-- Cluster lookup, for the "have we already seen this story" check.
CREATE INDEX IF NOT EXISTS trend_items_cluster_idx
    ON content.trend_items (cluster_key) WHERE cluster_key IS NOT NULL;
-- Retention sweep.
CREATE INDEX IF NOT EXISTS trend_items_surfaced_idx ON content.trend_items (surfaced_at);


-- ───────────────────────────────────────────────────────────────────────────
-- trend_sources — captured evidence. THE grounding corpus for external claims.
--
-- This table is what makes timely content publishable at all. The grounding
-- gate refuses any figure that does not appear either in the site-repo facts
-- snapshot (claims about WizCodes) or in an extract here (claims about the
-- world). An uncited external number is rejected exactly as an invented
-- WizCodes number is — the gate gets stricter, not looser.
--
-- It also means citations are free: you cannot cite what you did not capture,
-- and capturing to satisfy the gate leaves the citation already written.
--
-- Rows OUTLIVE the item that produced them. A published post's citation must
-- still resolve months later, so retention never deletes a source that an
-- angle referenced.
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS content.trend_sources (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trend_id     bigint REFERENCES content.trend_items (id) ON DELETE SET NULL,
    url          text NOT NULL,
    title        text,
    publisher    text,
    -- The extracted text the grounding gate greps. Not the whole page: enough
    -- to substantiate the specific claims, bounded so the table stays small.
    extract      text NOT NULL,
    -- When WE fetched it. Distinct from published_at, and the one that matters
    -- for "is this claim stale" — a 2019 article retrieved today is still a
    -- 2019 claim, and both dates are needed to tell.
    retrieved_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    relevance    real,
    CONSTRAINT trend_sources_uniq UNIQUE (trend_id, url)
);

CREATE INDEX IF NOT EXISTS trend_sources_trend_idx ON content.trend_sources (trend_id);


-- ───────────────────────────────────────────────────────────────────────────
-- trend_angles — the usable output: a verified story plus what it means.
-- Read by the Content Poster, and by the blog agent for topic selection.
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS content.trend_angles (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trend_id      bigint NOT NULL REFERENCES content.trend_items (id) ON DELETE CASCADE,

    headline      text NOT NULL,        -- the consequence, not the announcement
    so_what       text NOT NULL,        -- second-order effect for a business owner
    action        text,                 -- what they should actually do
    service_line  text CHECK (service_line IN
                      ('Web Development','Mobile Apps','AI Automation','none')),
    -- 'none' is the EXPECTED value for roughly four posts in five. A layer that
    -- ties every trend back to its own services is doing native advertising,
    -- and the ratio is the difference between value-first and transparent.

    -- Every hard claim, with the source row that substantiates it. The
    -- grounding gate reads this; the citation line renders from it.
    claims        jsonb NOT NULL DEFAULT '[]'::jsonb,
    citation      text,                 -- "Stack Overflow's 2026 survey" + URL

    -- Suitability, decided once at synthesis rather than re-argued per platform.
    good_for      jsonb NOT NULL DEFAULT '[]'::jsonb,   -- ["threads","linkedin","blog"]

    status        text NOT NULL DEFAULT 'ready'
                  CHECK (status IN ('ready','used','expired','blocked')),
    blocked_reason text,
    used_at       timestamptz,
    used_platform text,
    -- A stale take published late is worse than none, so an angle that ages out
    -- is deleted rather than queued. This is what the sweep reads.
    expires_at    timestamptz NOT NULL DEFAULT (now() + interval '48 hours'),
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- "What can I post right now?" — the Content Poster's only query here.
CREATE INDEX IF NOT EXISTS trend_angles_ready_idx
    ON content.trend_angles (expires_at)
    WHERE status = 'ready';
CREATE INDEX IF NOT EXISTS trend_angles_trend_idx ON content.trend_angles (trend_id);


-- ───────────────────────────────────────────────────────────────────────────
-- The off-calendar insert budget.
--
-- Timeliness is only worth something if a hot trend can be posted today rather
-- than on Thursday. But an agent that inserts freely stops having a rhythm at
-- all, and a learned schedule is most of why an audience returns. One insert
-- per platform per day: the rhythm is disturbed, not replaced.
--
-- A table rather than a counter in memory, because the cap is per DAY and a run
-- has no idea what earlier runs did.
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS content.trend_inserts (
    day        date NOT NULL,
    platform   text NOT NULL,
    angle_id   bigint REFERENCES content.trend_angles (id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (day, platform)
);
