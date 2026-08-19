"""The publishing interface.

Every platform is independently failable. One dead API is skipped and reported;
it never takes the run to zero and it never blocks the other three.

## Idempotency is not optional here

Publishing is irreversible. A timeout followed by a retry is the difference
between "the network blipped" and "we posted the same thing to Facebook three
times", and there is no un-post. So every publish claims a key in
`core.external_actions` **before** the API call and records the result after —
`wizcore.db.actions.claim` — and a claim whose outcome is unknown refuses rather
than guesses.

The key is derived from the calendar slot and the date, never from the generated
copy. If it were content-derived, a regenerated draft after a partial failure
would look like a brand-new action and publish twice.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import requests

log = logging.getLogger("content_poster.platforms")


@dataclass
class Draft:
    """What the writer produced, after validation, ready to publish."""

    platform: str
    pillar: str
    caption: str
    hashtags: list[str] = field(default_factory=list)
    slides: list[dict] = field(default_factory=list)
    image_urls: list[str] = field(default_factory=list)
    title: str = ""            # pinterest / dev.to
    link: str = ""             # the URL this post points at, if any
    body_markdown: str = ""    # dev.to only
    raw: dict = field(default_factory=dict)

    #: Platforms where a link in the body costs more reach than it earns.
    #:
    #: LinkedIn measurably suppresses posts carrying an external link in the
    #: body — that is why `first_comment()` exists — and Instagram captions do
    #: not linkify at all, so the text would be decoration a reader has to
    #: retype. Everywhere else the link is the whole point: somebody who wants
    #: what we build should not have to go looking for us.
    NO_BODY_LINK = frozenset({"linkedin", "instagram"})

    def rendered_caption(self, inline_hashtags: bool = True, site_url: str = "") -> str:
        """Caption, then the visit line, then the hashtags.

        Order matters. The call to action reads as the close of the post; put it
        after the hashtag block and it reads as an afterthought stapled on below
        a wall of tags.
        """
        parts = [self.caption]
        if site_url and self.platform not in self.NO_BODY_LINK:
            parts.append(f"Visit us: {site_url}")
        if inline_hashtags and self.hashtags:
            tags = " ".join(f"#{t.lstrip('#')}" for t in self.hashtags if t.strip())
            if tags:
                parts.append(tags)
        return "\n\n".join(p for p in parts if p)


    def first_comment(self) -> str:
        """What belongs under the post rather than in it.

        Two things end up here for the same reason — LinkedIn measurably
        suppresses reach for posts carrying an external link in the body, and
        Instagram treats caption hashtags as clutter:

          - the citation URL for a timely post
          - the hashtag block on Instagram

        This is how a post can be both properly cited and not penalised for it.
        """
        parts: list[str] = []
        if self.link:
            parts.append(f"Source: {self.link}")
        return "\n".join(parts)


@dataclass
class PublishResult:
    platform: str
    ok: bool
    external_id: str = ""
    permalink: str = ""
    error: str = ""
    skipped: bool = False

    @classmethod
    def failure(cls, platform: str, error: str) -> PublishResult:
        return cls(platform=platform, ok=False, error=str(error)[:500])

    @classmethod
    def skip(cls, platform: str, why: str) -> PublishResult:
        return cls(platform=platform, ok=True, skipped=True, error=why[:300])


class Platform(ABC):
    name: str = "base"
    # Platforms whose publish API fetches the image by URL rather than accepting
    # an upload. These cannot run without R2.
    needs_hosted_images: bool = False

    def __init__(self, config):
        self.config = config

    @abstractmethod
    def publish(self, draft: Draft) -> PublishResult:
        """Publish, or return a failure. Must not raise."""

    # ── shared HTTP ──
    def _post(self, url: str, **kw) -> requests.Response:
        kw.setdefault("timeout", self.config.http_timeout)
        return requests.post(url, **kw)

    def _get(self, url: str, **kw) -> requests.Response:
        kw.setdefault("timeout", self.config.http_timeout)
        return requests.get(url, **kw)

    @staticmethod
    def _api_error(resp: requests.Response) -> str:
        """A readable reason from a platform error body.

        Meta nests the useful part under error.message and puts an unhelpful
        generic string at the top level, so unwrapping it here saves reading raw
        JSON out of a Telegram alert at 2am.
        """
        try:
            payload = resp.json()
        except ValueError:
            return f"HTTP {resp.status_code}: {resp.text[:200]}"
        err = payload.get("error")
        if isinstance(err, dict):
            detail = err.get("error_user_msg") or err.get("message") or str(err)
            return f"HTTP {resp.status_code}: {detail}"[:400]
        return f"HTTP {resp.status_code}: {str(payload)[:200]}"
