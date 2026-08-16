"""Platform registry.

Enabling a platform is one env var. Every entry here is fully implemented,
including the two that are dormant: LinkedIn (API in review) and dev.to
(event-driven rather than scheduled). Writing them now means switching them on
later is a config change, not a build under time pressure.
"""
from __future__ import annotations

from platforms.base import Draft, Platform, PublishResult
from platforms.devto import DevToPlatform
from platforms.facebook import FacebookPlatform
from platforms.instagram import InstagramPlatform
from platforms.linkedin import LinkedInPlatform
from platforms.manual import ManualPlatform
from platforms.pinterest import PinterestPlatform
from platforms.threads import ThreadsPlatform

REGISTRY: dict[str, type[Platform]] = {
    "facebook": FacebookPlatform,
    "threads": ThreadsPlatform,
    "instagram": InstagramPlatform,
    "pinterest": PinterestPlatform,
    "linkedin": LinkedInPlatform,
    "devto": DevToPlatform,
    # No API exists for these; the agent writes and a human posts.
    "x": ManualPlatform,
    "youtube": ManualPlatform,
    # Reddit is hand-posted by policy rather than by API limitation: a person
    # has to choose the subreddit and judge whether it is welcome there.
    "reddit": ManualPlatform,
}


def get_platform(name: str, config) -> Platform:
    """The client for a platform, or the manual queue if it is hand-posted.

    `PLATFORMS_MANUAL` wins over the registry so a platform with a finished API
    client can still be posted by hand while its token is pending. Resolving it
    here rather than at each call site means every path — scheduled posts,
    timely inserts, previews — agrees on which platforms are automatic, and
    switching one back is deleting a name from an env var.
    """
    if name in getattr(config, "platforms_manual", ()):
        return ManualPlatform(config)
    return REGISTRY[name](config)


__all__ = ["REGISTRY", "Draft", "Platform", "PublishResult", "get_platform"]
