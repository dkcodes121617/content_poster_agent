"""Graph state for the Content Poster.

Unlike the Lead Finder, nothing here fans out concurrently — slots are published
in sequence so a rate limit on one platform cannot cascade — so no key needs an
`operator.add` reducer. Every field is written by exactly one node.
"""
from __future__ import annotations

from typing import Any, TypedDict


class PosterState(TypedDict, total=False):
    run_id: str
    now_iso: str
    facts_block: str
    history: list[str]
    due: list[Any]           # calendar.Slot
    drafts: list[Any]        # platforms.Draft
    rejected: list[dict]     # {platform, pillar, reasons}
    results: list[Any]       # platforms.PublishResult
    counters: dict[str, Any]
