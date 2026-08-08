"""Threads publishing — the two-step create-then-publish flow.

Threads (like Instagram) does not take a post in one call: you create a media
container, then publish it by id. Both steps must succeed, and a container
created but never published is an invisible orphan rather than an error — which
is why the second step's failure is reported explicitly instead of being
inferred from silence.

Text-first by design: Threads rewards conversational one- and two-sentence posts
and this is the highest-cadence platform in the campaign at five a week, so the
image is optional here in a way it is not on Facebook or Instagram.
"""
from __future__ import annotations

import logging
import time

from platforms.base import Draft, Platform, PublishResult

log = logging.getLogger("content_poster.platforms.threads")

_BASE = "https://graph.threads.net/v1.0"


class ThreadsPlatform(Platform):
    name = "threads"
    needs_hosted_images = False

    def publish(self, draft: Draft) -> PublishResult:
        token = self.config.live_threads_token
        text = draft.rendered_caption()

        params = {"text": text, "access_token": token}
        if draft.image_urls:
            params["media_type"] = "IMAGE"
            params["image_url"] = draft.image_urls[0]
        else:
            params["media_type"] = "TEXT"

        try:
            created = self._post(f"{_BASE}/me/threads", data=params)
        except Exception as e:
            return PublishResult.failure(self.name, f"network on create: {e}")
        if created.status_code != 200:
            return PublishResult.failure(self.name, "create: " + self._api_error(created))

        container_id = str(created.json().get("id") or "")
        if not container_id:
            return PublishResult.failure(self.name, "create returned no container id")

        # Threads needs a moment to process a container before it will publish
        # it; publishing immediately intermittently returns "media not ready".
        time.sleep(3)

        try:
            published = self._post(
                f"{_BASE}/me/threads_publish",
                data={"creation_id": container_id, "access_token": token},
            )
        except Exception as e:
            return PublishResult.failure(
                self.name, f"network on publish (container {container_id} orphaned): {e}"
            )
        if published.status_code != 200:
            return PublishResult.failure(
                self.name,
                f"publish (container {container_id} orphaned): " + self._api_error(published),
            )

        post_id = str(published.json().get("id") or "")

        # The citation goes under the post, not in it. A timely post that cites
        # nothing is not credible; one with a URL in the body reaches fewer
        # people. A reply gets both.
        comment = draft.first_comment()
        if comment and post_id:
            self._reply(token, post_id, comment)

        permalink = ""
        try:
            info = self._get(
                f"{_BASE}/{post_id}", params={"fields": "permalink", "access_token": token}
            )
            if info.status_code == 200:
                permalink = info.json().get("permalink", "")
        except Exception:
            # The post is live; a missing permalink only costs a nicer Telegram
            # message and must not turn a success into a failure.
            pass

        return PublishResult(
            platform=self.name, ok=True, external_id=post_id, permalink=permalink
        )

    def _reply(self, token: str, post_id: str, text: str) -> None:
        """Post a reply to our own thread. Never fails the publish.

        The post is already live by this point. Losing the citation costs some
        credibility; turning a successful publish into a failure would cost the
        post and leave the idempotency claim refusing a retry.
        """
        try:
            created = self._post(
                f"{_BASE}/me/threads",
                data={
                    "media_type": "TEXT",
                    "text": text,
                    "reply_to_id": post_id,
                    "access_token": token,
                },
            )
            if created.status_code != 200:
                log.warning("citation reply failed: %s", self._api_error(created))
                return
            container = str(created.json().get("id") or "")
            if not container:
                return
            time.sleep(2)
            self._post(
                f"{_BASE}/me/threads_publish",
                data={"creation_id": container, "access_token": token},
            )
        except Exception:
            log.warning("citation reply failed", exc_info=True)
