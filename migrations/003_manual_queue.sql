-- ═══════════════════════════════════════════════════════════════════════════
-- Content Poster 003 — the manual hand-off queue (X threads, YouTube Shorts)
-- ═══════════════════════════════════════════════════════════════════════════
-- X and YouTube have no usable free API, so the agent writes the content and a
-- human posts it. Without a table, "handed over" and "actually posted" are the
-- same thing, and an item that scrolls past in Telegram is simply lost — which
-- is precisely the silent-drop failure this system is built to avoid.
--
-- NAMING: ARCHITECTURE.md §5.1 calls this `core.manual_queue`. It lives in
-- `content` instead, deliberately. `core` is owned by lead_finder_agent's
-- migrations — that is what makes "run the Lead Finder's migrations first on a
-- fresh database" a rule rather than a coincidence — and adding a
-- Content-Poster-only table there would put one agent's schema change in
-- another agent's migration folder. The digest reads across schemas anyway, so
-- nothing is lost by keeping ownership honest.
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS content.manual_queue (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id       uuid REFERENCES core.agent_runs (run_id) ON DELETE SET NULL,
    platform     text NOT NULL CHECK (platform IN ('x', 'youtube', 'gbp')),
    pillar       text,
    -- The copy, formatted for copy-paste. For an X thread this is the numbered
    -- tweets separated by blank lines.
    body         text NOT NULL,
    hashtags     jsonb NOT NULL DEFAULT '[]'::jsonb,
    image_urls   jsonb NOT NULL DEFAULT '[]'::jsonb,
    -- pending  : handed over, not yet posted
    -- done     : the owner confirmed with /done <id>
    -- expired  : aged out; surfaced in the digest rather than deleted
    status       text NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'done', 'expired')),
    -- Same idempotency discipline as a real publish: one hand-over per slot per
    -- day, so a re-run cannot flood Telegram with duplicates of the same thread.
    idempotency_key text UNIQUE,
    created_at   timestamptz NOT NULL DEFAULT now(),
    done_at      timestamptz
);

CREATE INDEX IF NOT EXISTS manual_queue_pending_idx
    ON content.manual_queue (created_at)
    WHERE status = 'pending';
