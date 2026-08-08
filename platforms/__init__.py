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
}


def get_platform(name: str, config) -> Platform:
    return REGISTRY[name](config)


__all__ = ["REGISTRY", "Draft", "Platform", "PublishResult", "get_platform"]
