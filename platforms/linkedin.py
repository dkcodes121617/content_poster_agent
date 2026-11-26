"""LinkedIn company page: text, single image, or a swipeable document carousel.

Posts go to the documented `/rest/posts` endpoint as the organization.

What a post carries depends on what the render node produced:

  - several slides -> one PDF, uploaded through the Documents API. LinkedIn
    shows a PDF as the native swipeable carousel, which is the format that
    earns reach on a B2B feed. (Its old "multi-image" grid looks like an album,
    not a deck.)
  - one slide      -> one image through the Images API.
  - nothing        -> text only (the render node failed open, or a test).

Media is uploaded as bytes, never fetched by URL, so this needs no R2 hosting.
LinkedIn processes an upload asynchronously: posting before the asset is
AVAILABLE can create a post with a broken attachment, so we wait for it.

The link rule is the reason this platform has its own validator case: LinkedIn
suppresses reach for posts carrying an external link in the body, so the link
goes in the first comment. Nothing rejects such a post — it just quietly reaches
far fewer people, which is exactly what a human reviewer would never notice.
"""
from __future__ import annotations

import io
import logging
import time
from pathlib import Path
from urllib.parse import quote

from platforms.base import Draft, Platform, PublishResult

log = logging.getLogger("content_poster.platforms.linkedin")

_BASE = "https://api.linkedin.com/rest"
# LinkedIn versions its API by date header and rejects requests without one.
# Each monthly version is sunset about a year after release - 202506 was already
# retired by Oct 2026 (202510 sunsets 15 Oct 2026) - so a version pinned at
# build time silently becomes a 100%-failure publisher. Keep in step with
# tools/linkedin_auth.py.
_VERSION = "202609"

# How long to wait for LinkedIn to finish processing an upload.
_PROCESS_WAIT_S = 60
_PROCESS_POLL_S = 3


class MediaError(RuntimeError):
    """An upload step failed. The post is not made with a missing attachment."""


def build_pdf(paths: list[Path]) -> bytes:
    """Slides -> one PDF, one page per slide, at the slides' own size."""
    from PIL import Image

    pages = []
    for p in paths:
        with Image.open(p) as im:
            pages.append(im.convert("RGB"))
    if not pages:
        raise MediaError("no slides to build a document from")
    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:], resolution=150.0)
    return buf.getvalue()


def document_title(draft: Draft) -> str:
    """The title LinkedIn shows on the carousel. First slide's title, else caption."""
    for slide in draft.slides or []:
        title = str(slide.get("title") or "").strip()
        if title:
            return title[:120]
    if draft.title:
        return draft.title[:120]
    first = (draft.caption or "").strip().split("\n", 1)[0]
    return (first[:117] + "...") if len(first) > 120 else (first or "WizCodes")


class LinkedInPlatform(Platform):
    name = "linkedin"
    needs_hosted_images = False
    needs_images = True

    def _headers(self, token: str, json_body: bool = True) -> dict:
        h = {
            "Authorization": f"Bearer {token}",
            "LinkedIn-Version": _VERSION,
            "X-Restli-Protocol-Version": "2.0.0",
        }
        if json_body:
            h["Content-Type"] = "application/json"
        return h

    # ── media ──
    def _upload(self, kind: str, data: bytes, token: str, owner: str) -> str:
        """Upload bytes through /rest/{kind} (images or documents). Returns the URN."""
        resp = self._post(
            f"{_BASE}/{kind}?action=initializeUpload",
            json={"initializeUploadRequest": {"owner": owner}},
            headers=self._headers(token),
        )
        if resp.status_code not in (200, 201):
            raise MediaError(f"{kind} initializeUpload: {self._api_error(resp)}")
        value = (resp.json() or {}).get("value") or {}
        upload_url = value.get("uploadUrl")
        urn = value.get("image") or value.get("document")
        if not (upload_url and urn):
            raise MediaError(f"{kind} initializeUpload returned no upload URL")

        put = self._put(
            upload_url,
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
            },
        )
        if put.status_code not in (200, 201):
            raise MediaError(f"{kind} upload: HTTP {put.status_code}: {put.text[:200]}")

        self._wait_available(kind, urn, token)
        return urn

    def _wait_available(self, kind: str, urn: str, token: str) -> None:
        deadline = time.monotonic() + _PROCESS_WAIT_S
        status = "unknown"
        while time.monotonic() < deadline:
            resp = self._get(
                f"{_BASE}/{kind}/{quote(urn, safe='')}",
                headers=self._headers(token, json_body=False),
            )
            if resp.status_code == 200:
                status = str((resp.json() or {}).get("status") or "")
                if status == "AVAILABLE":
                    return
                if status == "PROCESSING_FAILED":
                    raise MediaError(f"LinkedIn could not process the {kind[:-1]} {urn}")
            time.sleep(_PROCESS_POLL_S)
        raise MediaError(f"{kind[:-1]} {urn} still {status or 'unprocessed'} after {_PROCESS_WAIT_S}s")

    def _media_content(self, draft: Draft, token: str, owner: str) -> dict | None:
        paths = [Path(p) for p in draft.raw.get("local_images") or [] if Path(p).exists()]
        if not paths:
            return None
        if len(paths) == 1:
            urn = self._upload("images", paths[0].read_bytes(), token, owner)
            return {"media": {"id": urn, "altText": document_title(draft)[:4086]}}
        urn = self._upload("documents", build_pdf(paths), token, owner)
        return {"media": {"id": urn, "title": document_title(draft)}}

    # ── publish ──
    def publish(self, draft: Draft) -> PublishResult:
        cfg = self.config
        token = cfg.live_linkedin_token
        if not (token and cfg.linkedin_org_id):
            return PublishResult.skip(
                self.name,
                "LinkedIn credentials are unset - Community Management API is still "
                "in review. Nothing else is blocked by this.",
            )

        author = f"urn:li:organization:{cfg.linkedin_org_id}"
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

        # A post written around its slides must not go out without them, so a
        # media failure fails the publish rather than degrading to text.
        try:
            content = self._media_content(draft, token, author)
        except MediaError as e:
            return PublishResult.failure(self.name, f"media: {e}")
        except Exception as e:
            return PublishResult.failure(self.name, f"media network: {e}")
        if content:
            payload["content"] = content

        try:
            resp = self._post(f"{_BASE}/posts", json=payload, headers=self._headers(token))
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
