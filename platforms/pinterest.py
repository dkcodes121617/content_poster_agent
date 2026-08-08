"""Pinterest — long-tail visual search.

**A Pin with no board 400s.** The account currently has zero boards, so this
platform reports a clear skip rather than a cryptic API error until
`PINTEREST_BOARD_ID` is set. That is an owner action, not a code one.

No hashtags: keywords in the description do the work on Pinterest, and tags read
as noise there.

## There is no permanent Pinterest token

Three lifetimes, and picking the wrong one is why this platform broke once
already:

  - **test token** from the app dashboard — **24 hours**, not refreshable. It is
    for poking at the API by hand, and it is what was originally configured.
  - **access token** from the OAuth flow — 30 days (2,592,000 s).
  - **continuous refresh token** — 60 days, but **refreshable indefinitely**.

So "permanent" is achieved the same way Instagram's is: authorise once, keep the
refresh token, refresh on a cron. `refresh()` below is that cron's job. A token
whose refresh is a calendar reminder is a token that will eventually lapse
unnoticed on a Sunday.
"""
from __future__ import annotations

import base64
import logging

from platforms.base import Draft, Platform, PublishResult

log = logging.getLogger("content_poster.platforms.pinterest")

_BASE = "https://api.pinterest.com/v5"


class PinterestPlatform(Platform):
    name = "pinterest"
    needs_hosted_images = True

    def publish(self, draft: Draft) -> PublishResult:
        if not self.config.pinterest_board_id:
            return PublishResult.skip(
                self.name,
                "PINTEREST_BOARD_ID is not set - a Pin with no board returns 400. "
                "Create one board in Pinterest, then set the id.",
            )
        if not draft.image_urls:
            return PublishResult.failure(self.name, "no image URL; a Pin needs one image")

        payload = {
            "board_id": self.config.pinterest_board_id,
            "title": (draft.title or draft.caption)[:100],
            "description": draft.caption[:500],
            "media_source": {
                "source_type": "image_url",
                "url": draft.image_urls[0],
            },
        }
        if draft.link:
            payload["link"] = draft.link

        try:
            resp = self._post(
                f"{_BASE}/pins",
                json=payload,
                headers={"Authorization": f"Bearer {self.config.live_pinterest_token}"},
            )
        except Exception as e:
            return PublishResult.failure(self.name, f"network: {e}")

        if resp.status_code not in (200, 201):
            return PublishResult.failure(self.name, self._api_error(resp))

        pin_id = str(resp.json().get("id") or "")
        return PublishResult(
            platform=self.name,
            ok=True,
            external_id=pin_id,
            permalink=f"https://www.pinterest.com/pin/{pin_id}/" if pin_id else "",
        )

    # ── token maintenance ──
    def refresh(self) -> tuple[bool, str, dict]:
        """Exchange the refresh token for a fresh access token.

        Returns `(ok, detail, values)` where `values` holds any new
        `PINTEREST_TOKEN` / `PINTEREST_REFRESH_TOKEN` to persist.

        Pinterest rotates the refresh token on some responses and omits it on
        others. When it is omitted the existing one stays valid — so the caller
        must only write back what actually came in, or it would blank a working
        credential and turn a routine refresh into a dead integration.
        """
        cfg = self.config
        if not (cfg.pinterest_refresh_token and cfg.pinterest_app_id and cfg.pinterest_app_secret):
            return False, (
                "PINTEREST_REFRESH_TOKEN / APP_ID / APP_SECRET not set - the current "
                "token is a 24-hour dashboard test token and cannot be refreshed. "
                "Run tools/pinterest_auth.py once."
            ), {}

        basic = base64.b64encode(
            f"{cfg.pinterest_app_id}:{cfg.pinterest_app_secret}".encode()
        ).decode()
        try:
            resp = self._post(
                f"{_BASE}/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": cfg.pinterest_refresh_token,
                },
                headers={
                    "Authorization": f"Basic {basic}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
        except Exception as e:
            return False, f"network: {e}", {}

        if resp.status_code != 200:
            return False, self._api_error(resp), {}

        payload = resp.json()
        values = {"PINTEREST_TOKEN": payload.get("access_token", "")}
        if payload.get("refresh_token"):
            values["PINTEREST_REFRESH_TOKEN"] = payload["refresh_token"]
        expires_in = int(payload.get("expires_in") or 0)
        return True, f"access token refreshed, {expires_in // 86400}d", values

    def boards(self) -> tuple[bool, list[dict]]:
        """List boards. A Pin with no board 400s, so this is worth checking."""
        try:
            resp = self._get(
                f"{_BASE}/boards",
                headers={"Authorization": f"Bearer {self.config.live_pinterest_token}"},
                params={"page_size": 25},
            )
            if resp.status_code != 200:
                return False, []
            return True, resp.json().get("items", [])
        except Exception:
            return False, []
