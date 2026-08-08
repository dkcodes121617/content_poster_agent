-- ═══════════════════════════════════════════════════════════════════════════
-- Content Poster — the schema this agent owns
-- ═══════════════════════════════════════════════════════════════════════════
-- Depends on the shared `core` schema, which is owned by the Lead Finder
-- (lead_finder_agent/migrations/001_core.sql). Run that first on a fresh
-- database; the foreign key below is what makes the ordering explicit rather
-- than a convention someone has to remember.
--
-- This agent WRITES: content.*, core.external_actions, core.agent_runs,
-- and its own rows in cp_ckpt.*. It READS core.approval_events.
-- It never writes core.leads.
-- ═══════════════════════════════════════════════════════════════════════════

CREATE SCHEMA IF NOT EXISTS content;

-- The LangGraph checkpointer's own schema. Separate per agent on purpose:
-- PostgresSaver keys rows by thread_id alone, so a shared schema plus any
-- run_id collision means one agent resuming another agent's run.
CREATE SCHEMA IF NOT EXISTS cp_ckpt;


-- Which published page has already been promoted, so the blog_teaser /
-- case_study rotation never re-posts the same asset. This is what turns the
-- blog and case-study agents' output into distribution without coupling the
-- three agents to each other.
CREATE TABLE IF NOT EXISTS content.promoted_assets (
    asset_type   text NOT NULL CHECK (asset_type IN ('blog','case_study','project')),
    slug         text NOT NULL,
    promoted_at  timestamptz NOT NULL DEFAULT now(),
    platforms    jsonb NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY (asset_type, slug)
);

CREATE TABLE IF NOT EXISTS content.social_posts (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id           uuid REFERENCES core.agent_runs (run_id) ON DELETE SET NULL,
    content_type     text NOT NULL,
    platform         text NOT NULL,
    external_post_id text,
    permalink        text,
    status           text NOT NULL CHECK (status IN ('published','failed','skipped')),
    error            text,
    published_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS social_posts_recent_idx
    ON content.social_posts (platform, published_at DESC);
