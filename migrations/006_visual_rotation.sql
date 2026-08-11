-- ═══════════════════════════════════════════════════════════════════════════
-- Content Poster 006 — the rotation ledger and the posting plan
-- ═══════════════════════════════════════════════════════════════════════════
-- Two tables that exist for the same reason: **a rule nobody records is a hope.**
--
--   visual_history  what a deck LOOKED like, so variety is a property
--   posting_plan    how much to publish where, so a ramp is a row not a deploy
--
-- Both are Content Poster only. No other agent reads or writes either.
-- ═══════════════════════════════════════════════════════════════════════════

-- ───────────────────────────────────────────────────────────────────────────
-- visual_history — CONTENT_SYSTEM.md §3.4
--
-- The repetition gate already stops month three sounding like month one. This
-- is the same discipline applied to design rather than words, and it is the
-- part that actually guarantees variety: the archetype registry makes variety
-- POSSIBLE, and without a ledger the picker would still land on the same
-- comfortable recipe every Monday. "Use variety" is a hope; "never the same
-- recipe twice in fourteen days on one platform" is a query.
--
-- Deliberately separate from content.social_posts even though every row has a
-- matching post. social_posts records what was published — it is written after
-- the API call, and only on success. The rotation decision has to be made
-- BEFORE anything is drafted, and has to count a deck that was rendered and
-- then rejected by a validator, because that deck still used up its turn as
-- far as "what did the last fortnight look like" is concerned.
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS content.visual_history (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    platform    text NOT NULL,
    pillar      text NOT NULL,
    recipe      text NOT NULL,
    -- The full sequence, in order. Stored as an array rather than a count so
    -- "never the same opener twice in a row" is answerable, and so archetype
    -- performance is answerable later without a migration (§8.4 — nothing
    -- ingests engagement data today; storing the field now costs nothing).
    archetypes  text[] NOT NULL DEFAULT '{}',
    layouts     text[] NOT NULL DEFAULT '{}',
    theme       text,
    region      text,
    posted_at   timestamptz NOT NULL DEFAULT now(),
    run_id      text
);

-- The only query this table serves: "what has this platform looked like
-- lately". Descending, because every read wants the most recent N.
CREATE INDEX IF NOT EXISTS visual_history_platform_time
    ON content.visual_history (platform, posted_at DESC);

-- ───────────────────────────────────────────────────────────────────────────
-- posting_plan — CONTENT_SYSTEM.md §5
--
-- Replaces the fixed 17-slot calendar with a target per day per platform, so
-- the day LinkedIn's API review clears, catching up is an UPDATE rather than a
-- code change and a deploy.
--
-- `effective_from` makes it a history rather than a setting: the weekly step-up
-- from launch rate to steady rate is a handful of future-dated rows written
-- once, and the scheduler reads whichever row is currently in force. That also
-- means a ramp can be inspected before it happens instead of being discovered
-- afterwards.
--
-- The ceilings are not advisory. §5 argues, at length, that a brand-new
-- LinkedIn page posting five times a day is indistinguishable from spam to both
-- the algorithm and a human visitor, and that early-page reach penalties are
-- sticky. `hard_ceiling` is where that argument is enforced rather than
-- remembered.
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS content.posting_plan (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    platform        text NOT NULL,
    target_per_day  numeric(4,2) NOT NULL CHECK (target_per_day >= 0),
    hard_ceiling    numeric(4,2) NOT NULL CHECK (hard_ceiling > 0),
    effective_from  date NOT NULL DEFAULT CURRENT_DATE,
    note            text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT posting_plan_within_ceiling CHECK (target_per_day <= hard_ceiling),
    -- One plan per platform per day. A re-run of the ramp writer must be a
    -- no-op, not a second row that silently doubles the target.
    CONSTRAINT posting_plan_one_per_day UNIQUE (platform, effective_from)
);

CREATE INDEX IF NOT EXISTS posting_plan_lookup
    ON content.posting_plan (platform, effective_from DESC);

-- ───────────────────────────────────────────────────────────────────────────
-- Backfill support — §5.
--
-- When a platform switches on, the honest form of "catching up" is republishing
-- posts that were already written, already validated and already good, and that
-- nobody on the new platform has seen. This records what has been reused where,
-- so the same post cannot be backfilled to the same platform twice.
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS content.backfill_log (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_post_id bigint NOT NULL REFERENCES content.social_posts(id) ON DELETE CASCADE,
    platform       text NOT NULL,
    posted_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT backfill_once UNIQUE (source_post_id, platform)
);
