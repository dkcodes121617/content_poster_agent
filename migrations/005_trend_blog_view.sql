-- ═══════════════════════════════════════════════════════════════════════════
-- Content Poster 005 — the blog agent's read surface
-- ═══════════════════════════════════════════════════════════════════════════
-- TRENDS.md §7: the highest-leverage output of the trend layer is not a social
-- post. A social post spikes for a day; a blog page that answers the question
-- people are searching ranks for a year, and gets cited by generative search
-- (GEO) and retrieved by LLMs (LLMO). SEO, AEO, GEO and LLMO all apply to the
-- blog and effectively none of them apply to an Instagram caption.
--
-- The blog agent lives in a different repo and cannot import anything from this
-- one. So the interface is a VIEW — the narrowest possible contract, readable
-- with one SELECT and no knowledge of how any of this works.
--
-- It reads. It never writes. `used_at` on the angle stays owned by the Content
-- Poster, so the two agents cannot race over the same row: a blog post and a
-- social post about the same trend are complementary, not duplicates.
-- ═══════════════════════════════════════════════════════════════════════════

CREATE OR REPLACE VIEW content.blog_trend_topics AS
    SELECT
        a.id                AS angle_id,
        a.trend_id,
        a.headline,
        a.so_what,
        a.action,
        a.service_line,
        a.citation,
        a.claims,
        i.relevance,
        i.title            AS source_title,
        i.url              AS source_url,
        i.surfaced_at,
        -- Every captured extract for this trend, so the blog agent can ground
        -- and cite without re-fetching anything. This is the same corpus the
        -- social grounding gate reads, which is what keeps a blog post and a
        -- social post about one story factually identical.
        (
            SELECT jsonb_agg(jsonb_build_object(
                       'url', s.url,
                       'title', s.title,
                       'publisher', s.publisher,
                       'extract', s.extract,
                       'retrieved_at', s.retrieved_at))
            FROM content.trend_sources s
            WHERE s.trend_id = a.trend_id
        )                  AS sources
    FROM content.trend_angles a
    JOIN content.trend_items i ON i.id = a.trend_id
    -- 'used' is included on purpose: a trend already posted to social is a
    -- PROVEN topic, and the blog post promoting it is the compounding half of
    -- the play. Only expired and blocked angles are excluded.
    WHERE a.status IN ('ready', 'used')
      AND a.created_at > now() - interval '30 days'
    ORDER BY i.relevance DESC NULLS LAST, a.created_at DESC;

COMMENT ON VIEW content.blog_trend_topics IS
    'Read-only topic feed for the blog agent (TRENDS.md §7). Verified trends '
    'with their captured sources, so a post can be grounded and cited without '
    'refetching. Written by content_poster_agent; never written by a reader.';
