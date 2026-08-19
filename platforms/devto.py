"""dev.to syndication — the cheapest reach in the campaign.

One API call republishes a blog post the blog agent already wrote, to a
developer audience, with a canonical URL pointing back at wizcodes.site. The
canonical tag is the whole point: without it this competes with the original for
the same search terms instead of feeding it.

Unlike every other platform here this is not scheduled by the calendar — it
fires when the blog agent publishes something not yet in
`content.promoted_assets`.
"""
from __future__ import annotations

import re

from platforms.base import Draft, Platform, PublishResult

_BASE = "https://dev.to/api"




def _tags(raw: list[str]) -> list[str]:
    """dev.to tags must be alphanumeric — no spaces, no punctuation.

    The previous version lowercased and truncated but kept spaces, so every
    multi-word tag the campaign produces ("custom crm", "roi calculator") was
    rejected and took the whole article with it:

        HTTP 422 Tag "custom crm" contains non-alphanumeric or prohibited
        unicode characters

    Three syndication attempts failed this way, one per day, each looking like
    a dev.to outage rather than a payload we built wrong.

    Stripping happens BEFORE truncation, which also fixes a second-order
    silliness: cutting "business intelligence" at 20 characters produced the
    tag "business intelligenc".
    """
    out: list[str] = []
    for tag in raw:
        clean = re.sub(r"[^a-z0-9]", "", str(tag).lower())[:20]
        if clean and clean not in out:
            out.append(clean)
    return out[:4]


class DevToPlatform(Platform):
    name = "devto"
    needs_hosted_images = False

    def publish(self, draft: Draft) -> PublishResult:
        if not draft.body_markdown:
            return PublishResult.failure(self.name, "no article body to syndicate")
        if not draft.link:
            return PublishResult.failure(
                self.name,
                "no canonical URL - syndicating without one makes this compete with "
                "the original post rather than feed it",
            )

        payload = {
            "article": {
                "title": (draft.title or draft.caption)[:128],
                "published": True,
                "body_markdown": draft.body_markdown,
                # Points search engines back at wizcodes.site.
                "canonical_url": draft.link,
                "tags": _tags(draft.hashtags),
            }
        }
        try:
            resp = self._post(
                f"{_BASE}/articles",
                json=payload,
                headers={
                    "api-key": self.config.devto_api_key,
                    "Content-Type": "application/json",
                },
            )
        except Exception as e:
            return PublishResult.failure(self.name, f"network: {e}")

        if resp.status_code not in (200, 201):
            return PublishResult.failure(self.name, self._api_error(resp))

        payload = resp.json()
        return PublishResult(
            platform=self.name,
            ok=True,
            external_id=str(payload.get("id") or ""),
            permalink=payload.get("url", ""),
        )
