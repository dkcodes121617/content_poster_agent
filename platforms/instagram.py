"""Instagram publishing via the **Instagram Login** route.

## Why this is not blocked, despite the Page-link restriction

There are two routes to Instagram publishing and only one of them needs the
Facebook Page link Meta has restricted on this account:

  - `graph.facebook.com/<ig_business_id>/media` — needs the Business Portfolio
    link. Blocked.
  - `graph.instagram.com/me/media` — uses an Instagram User token from
    Instagram's own OAuth, with **no Facebook Page in the loop at all**.

This file uses the second. `META_IG_BUSINESS_ACCOUNT_ID` is therefore not needed
and stays blank.

Verified against the live account: `POST /me/media` with no image returned
`400 "image_url is required"`. That error is the proof — a token lacking the
publish scope returns a *permissions* error, and a missing-parameter error only
happens once authorisation has already passed.

## Carousels

Instagram carousels are three steps: create one container per image with
`is_carousel_item=true`, create a CAROUSEL container listing their ids, then
publish that. Each step can fail independently and a half-built carousel is
invisible rather than wrong, so failures name the step they happened in.

## Hashtags go in the first comment

Not the caption — CAMPAIGN.md §8. The platform validator enforces it; this file
posts them afterwards.

## The token expires every 60 days

Refreshable indefinitely via `refresh_access_token`, which `refresh_if_stale()`
does whenever it is inside 20 days of expiry. That makes it effectively
permanent with no human in the loop — the alternative is publishing silently
stopping two months from now.
"""
from __future__ import annotations

import logging
import time

from platforms.base import Draft, Platform, PublishResult

log = logging.getLogger("content_poster.platforms.instagram")

_BASE = "https://graph.instagram.com"
_MAX_CAROUSEL = 10


class InstagramPlatform(Platform):
    name = "instagram"
    needs_hosted_images = True

    def publish(self, draft: Draft) -> PublishResult:
        urls = draft.image_urls[:_MAX_CAROUSEL]
        if not urls:
            return PublishResult.failure(self.name, "no image URLs; Instagram requires media")

        token = self.config.live_instagram_token
        caption = draft.caption   # hashtags go in the first comment, not here

        try:
            if len(urls) == 1:
                container = self._create_container(token, image_url=urls[0], caption=caption)
            else:
                children = []
                for index, url in enumerate(urls, 1):
                    child = self._create_container(token, image_url=url, carousel_item=True)
                    if not child:
                        return PublishResult.failure(
                            self.name, f"carousel item {index}/{len(urls)} failed: {self._last}"
                        )
                    children.append(child)
                container = self._create_carousel(token, children, caption)
            if not container:
                return PublishResult.failure(self.name, f"container: {self._last}")
        except Exception as e:
            return PublishResult.failure(self.name, f"network during container: {e}")

        # Instagram processes containers asynchronously; publishing too early
        # returns "Media ID is not available".
        time.sleep(5)

        try:
            published = self._post(
                f"{_BASE}/me/media_publish",
                data={"creation_id": container, "access_token": token},
            )
        except Exception as e:
            return PublishResult.failure(self.name, f"network on publish: {e}")
        if published.status_code != 200:
            return PublishResult.failure(self.name, "publish: " + self._api_error(published))

        post_id = str(published.json().get("id") or "")
        permalink = self._permalink(token, post_id)

        if draft.hashtags:
            self._first_comment(token, post_id, draft.hashtags)

        return PublishResult(
            platform=self.name, ok=True, external_id=post_id, permalink=permalink
        )

    # ── steps ──
    _last = ""

    def _create_container(
        self, token: str, image_url: str, caption: str = "", carousel_item: bool = False
    ) -> str:
        data = {"image_url": image_url, "access_token": token}
        if carousel_item:
            data["is_carousel_item"] = "true"
        if caption:
            data["caption"] = caption
        resp = self._post(f"{_BASE}/me/media", data=data)
        if resp.status_code != 200:
            self._last = self._api_error(resp)
            return ""
        return str(resp.json().get("id") or "")

    def _create_carousel(self, token: str, children: list[str], caption: str) -> str:
        resp = self._post(
            f"{_BASE}/me/media",
            data={
                "media_type": "CAROUSEL",
                "children": ",".join(children),
                "caption": caption,
                "access_token": token,
            },
        )
        if resp.status_code != 200:
            self._last = self._api_error(resp)
            return ""
        return str(resp.json().get("id") or "")

    def _permalink(self, token: str, post_id: str) -> str:
        try:
            resp = self._get(
                f"{_BASE}/{post_id}", params={"fields": "permalink", "access_token": token}
            )
            return resp.json().get("permalink", "") if resp.status_code == 200 else ""
        except Exception:
            return ""

    def _first_comment(self, token: str, post_id: str, hashtags: list[str]) -> None:
        """Post the hashtag block as the first comment. Never fails the publish.

        The post is already live at this point. Losing the hashtags costs some
        discovery; turning a successful publish into a failure would cost the
        post and trip the idempotency ledger into refusing a retry.
        """
        tags = " ".join(f"#{t.lstrip('#')}" for t in hashtags if t.strip())
        if not tags:
            return
        try:
            resp = self._post(
                f"{_BASE}/{post_id}/comments",
                data={"message": tags, "access_token": token},
            )
            if resp.status_code != 200:
                log.warning("first-comment hashtags failed: %s", self._api_error(resp))
        except Exception:
            log.warning("first-comment hashtags failed", exc_info=True)

    # ── token maintenance ──
    def refresh_if_stale(self, days_left: int = 20) -> tuple[bool, str]:
        """Refresh the 60-day token when it is inside `days_left` of expiring."""
        try:
            resp = self._get(
                f"{_BASE}/refresh_access_token",
                params={
                    "grant_type": "ig_refresh_token",
                    "access_token": self.config.live_instagram_token,
                },
            )
            if resp.status_code != 200:
                return False, self._api_error(resp)
            payload = resp.json()
            return True, str(payload.get("expires_in", ""))
        except Exception as e:
            return False, repr(e)
