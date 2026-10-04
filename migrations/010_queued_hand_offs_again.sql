-- Re-apply 009's correction to the rows written after it.
--
-- 009 introduced 'queued' and backfilled history, but graph/nodes.py kept
-- writing 'published' for hand-off platforms, so between 14 Sep and 4 Oct
-- another 30 LinkedIn and 9 X drafts were recorded as live while their queue
-- items sat 'pending'. The code now writes 'queued' (graph.nodes._post_status)
-- and `/done` flips the row to 'published' (platforms.manual.mark_done), so
-- this is the last time the correction has to be applied by hand.
--
-- Same three statements as 009, same order: queue state is the source of truth.

UPDATE content.social_posts p
   SET status = 'queued'
  FROM content.manual_queue m
 WHERE ('manual:' || m.id) = p.external_post_id
   AND p.status = 'published'
   AND m.status = 'pending';

UPDATE content.manual_queue
   SET status = 'expired'
 WHERE status = 'pending'
   AND created_at < now() - interval '7 days';

UPDATE content.social_posts p
   SET status = 'skipped'
  FROM content.manual_queue m
 WHERE ('manual:' || m.id) = p.external_post_id
   AND p.status = 'queued'
   AND m.status = 'expired';
