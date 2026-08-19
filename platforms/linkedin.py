"""LinkedIn — written now, dormant until the API review clears.

The Community Management API approval is the longest pole in the plan and blocks
nothing else, so this is implemented against the documented `/rest/posts`
endpoint and simply left out of `PLATFORMS_ENABLED`. When approval lands it is
one env-var edit, not a build.

The link rule is the reason this platform has its own validator case: LinkedIn
suppresses reach for posts carrying an external link in the body, so the link
goes in the first comment. Nothing rejects such a post — it just quietly reaches
far fewer people, which is exactly what a human reviewer would never notice.
"""
from __future__ import annotations

import logging

from platforms.base import Draft, Platform, PublishResult

log = logging.getLogger("content_poster.platforms.linkedin")

_BASE = "https://api.linkedin.com/rest"
# LinkedIn versions its API by date header and rejects requests without one.
_VERSION = "202506"


class LinkedInPlatform(Platform):
    name = "linkedin"
    needs_hosted_images = False

    def publish(self, draft: Draft) -> PublishResult:
        cfg = self.config
        if not (cfg.linkedin_token and cfg.linkedin_org_id):
            return PublishResult.skip(
                self.name,
                "LinkedIn credentials are unset - Community Management API is still "
                "in review. Nothing else is blocked by this.",
            )

        author = f"urn:li:organization:{cfg.linkedin_org_id}"
        headers = {
            "Authorization": f"Bearer {cfg.linkedin_token}",
            "LinkedIn-Version": _VERSION,
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }
        payload = {
            "author": author,
            # No site_url: LinkedIn suppresses body links, so it goes in the
            # first comment instead. See Draft.NO_BODY_LINK.
            "commentary": draft.rendered_caption(),
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }

        try:
            resp = self._post(f"{_BASE}/posts", json=payload, headers=headers)
        except Exception as e:
            return PublishResult.failure(self.name, f"network: {e}")

        if resp.status_code not in (200, 201):
            return PublishResult.failure(self.name, self._api_error(resp))

        post_id = resp.headers.get("x-restli-id", "") or str(resp.json().get("id", ""))
        return PublishResult(
            platform=self.name,
            ok=True,
            external_id=post_id,
            permalink=f"https://www.linkedin.com/feed/update/{post_id}/" if post_id else "",
        )
