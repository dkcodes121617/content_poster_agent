"""Facebook Page publishing via the Graph API.

The Page token is permanent — `debug_token` reports `expires_at = 0` — which is
a property of the token, not a guarantee about the account: revoking the app,
changing the password or a scope change all invalidate it. That is what
`core.credential_expiry` and the token watchdog are for, so publishing stopping
silently one morning becomes an alert rather than a mystery.

`/photos` rather than `/feed`: a photo post with a caption renders as an image
post, while `/feed` with a `link` renders as a link preview and reaches less.
"""
from __future__ import annotations

from platforms.base import Draft, Platform, PublishResult


class FacebookPlatform(Platform):
    name = "facebook"
    needs_hosted_images = True

    def publish(self, draft: Draft) -> PublishResult:
        cfg = self.config
        if not draft.image_urls:
            return PublishResult.failure(self.name, "no image URL; Facebook posts carry one image")

        base = f"https://graph.facebook.com/{cfg.meta_graph_version}"
        try:
            resp = self._post(
                f"{base}/{cfg.meta_page_id}/photos",
                data={
                    # Meta FETCHES this URL. It is never an upload, which is why
                    # R2 public access is a hard dependency of this path.
                    "url": draft.image_urls[0],
                    "caption": draft.rendered_caption(),
                    "published": "true",
                    "access_token": cfg.meta_page_token,
                },
            )
        except Exception as e:
            return PublishResult.failure(self.name, f"network: {e}")

        if resp.status_code != 200:
            return PublishResult.failure(self.name, self._api_error(resp))

        payload = resp.json()
        post_id = str(payload.get("post_id") or payload.get("id") or "")
        return PublishResult(
            platform=self.name,
            ok=True,
            external_id=post_id,
            permalink=f"https://www.facebook.com/{post_id}" if post_id else "",
        )
