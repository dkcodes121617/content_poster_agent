-- Separate "handed to a human" from "actually published".
--
-- `content.social_posts.status` had three values: published | failed | skipped.
-- Hand-posted platforms (X, LinkedIn today) write a row with
-- external_post_id = 'manual:<queue id>' and status = 'published' at the moment
-- the draft is QUEUED, not at the moment a human posts it. Nothing ever
-- corrected it afterwards, so:
--
--   * 52 of 145 rows (36%) claimed 'published' with no permalink and no real id
--   * exactly half of those were never posted at all - the queue item is still
--     'pending', some since 25 Aug
--   * every count of reach, including the agent_monitor dashboard, was inflated
--     by 36% and there was no way to tell the difference in SQL
--
-- 'queued' is the missing state. A row becomes 'published' when a human
-- confirms with /done, which is what flips the queue item to 'done'.
--
-- Backfill below is driven by the queue's own status, so a draft that really
-- was posted by hand keeps its 'published' row and only the genuinely
-- unposted ones move.

ALTER TABLE content.social_posts DROP CONSTRAINT IF EXISTS social_posts_status_check;

ALTER TABLE content.social_posts
  ADD CONSTRAINT social_posts_status_check
  CHECK (status = ANY (ARRAY['published'::text, 'queued'::text,
                             'failed'::text, 'skipped'::text]));

-- Only rows still waiting on a human. A queue item marked 'done' was genuinely
-- posted, so its row stays 'published' and stays in the reach numbers.
UPDATE content.social_posts p
   SET status = 'queued'
  FROM content.manual_queue m
 WHERE ('manual:' || m.id) = p.external_post_id
   AND p.status = 'published'
   AND m.status = 'pending';

-- Age out queue drafts nobody actioned. They are stale copy about trends that
-- have moved on, and leaving them 'pending' means the backlog never shrinks and
-- the daily message never stops asking for them.
UPDATE content.manual_queue
   SET status = 'expired'
 WHERE status = 'pending'
   AND created_at < now() - interval '7 days';

-- ...and move their posts to 'skipped', because an expired draft is never
-- going to be published by anyone.
UPDATE content.social_posts p
   SET status = 'skipped'
  FROM content.manual_queue m
 WHERE ('manual:' || m.id) = p.external_post_id
   AND p.status = 'queued'
   AND m.status = 'expired';
