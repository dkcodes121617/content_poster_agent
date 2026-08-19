-- Any platform can be hand-posted.
--
-- The queue's CHECK was a list of platforms that happened to have no API at the
-- time it was written. That is the wrong thing to encode: whether a platform is
-- hand-posted is an operational fact that changes the day a token arrives, not
-- a property of the platform.
--
-- It became load-bearing when Pinterest and Facebook were blocked by missing
-- permissions. The choice was to switch them off entirely — losing 19 weekly
-- slots of reach — or to let the agent keep writing and hand the result over.
-- The second is obviously better, and the CHECK was the only thing preventing
-- it.
--
-- PLATFORMS_MANUAL now decides which platforms route here. Deleting a name from
-- that variable is the whole of switching one back to publishing by API.

ALTER TABLE content.manual_queue
    DROP CONSTRAINT IF EXISTS manual_queue_platform_check;

ALTER TABLE content.manual_queue
    ADD CONSTRAINT manual_queue_platform_check
    CHECK (platform IN ('x', 'youtube', 'gbp', 'linkedin', 'reddit',
                        'facebook', 'pinterest', 'instagram', 'threads', 'devto'));
