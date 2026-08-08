-- ═══════════════════════════════════════════════════════════════════════════
-- Content Poster 002 — keep what was actually published
-- ═══════════════════════════════════════════════════════════════════════════
-- 001 recorded that a post happened (platform, id, permalink) but not what it
-- said. Three things need the text itself:
--
--   1. The repetition gate (CAMPAIGN.md §7.3) compares a draft against the last
--      60 published posts. With no stored text there is nothing to compare
--      against, and the gate that stops month three sounding like month one
--      silently passes everything.
--   2. Telegram reports what went out, so a post can be judged after the fact.
--   3. A pulled post needs a record of what it was.
--
-- Additive only: every column is nullable, so rows written by 001-era code stay
-- valid and no backfill is required.
-- ═══════════════════════════════════════════════════════════════════════════

ALTER TABLE content.social_posts
    ADD COLUMN IF NOT EXISTS caption      text,
    ADD COLUMN IF NOT EXISTS pillar       text,
    ADD COLUMN IF NOT EXISTS image_urls   jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS idempotency_key text;

-- The repetition gate's query: newest published captions first.
CREATE INDEX IF NOT EXISTS social_posts_published_caption_idx
    ON content.social_posts (published_at DESC)
    WHERE status = 'published' AND caption IS NOT NULL;

-- One row per external action. The ledger in core.external_actions is what
-- actually prevents a double post; this is the local record of which row that
-- claim produced, so a duplicate here is a bug worth catching rather than
-- tolerating.
CREATE UNIQUE INDEX IF NOT EXISTS social_posts_idem_idx
    ON content.social_posts (idempotency_key)
    WHERE idempotency_key IS NOT NULL;
