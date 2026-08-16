-- Widen the manual queue to every platform that can be hand-posted.
--
-- The original CHECK listed ('x','youtube','gbp'), which was true when it was
-- written and has been quietly wrong since Reddit was added to the platform
-- registry as a ManualPlatform. The insert in platforms/manual.py is wrapped in
-- a try/except that logs and returns None, so a Reddit item would have been
-- sent to Telegram and then silently NOT queued — invisible to the digest, the
-- dashboard, and `/done`. Exactly the "handed over and never posted" failure
-- the queue exists to prevent.
--
-- LinkedIn joins for a different reason: the API is implemented but has no
-- token yet, so it is hand-posted in the meantime. When the token arrives it
-- goes back to the API and this row type simply stops being produced — nothing
-- here needs reverting.

ALTER TABLE content.manual_queue
    DROP CONSTRAINT IF EXISTS manual_queue_platform_check;

ALTER TABLE content.manual_queue
    ADD CONSTRAINT manual_queue_platform_check
    CHECK (platform IN ('x', 'youtube', 'gbp', 'linkedin', 'reddit'));
