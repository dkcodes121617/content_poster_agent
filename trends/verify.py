"""Corroborate a trend and capture the evidence, via Tavily.

Two jobs, and the second is the one that matters:

1. **Corroborate.** A hard number from one source is a liability — breaking
   stories are wrong often enough that amplifying a single-sourced statistic is
   how a brand ends up issuing a correction. `TREND_MIN_SOURCES` (default 2)
   independent sources are required before a figure may be *asserted*.

2. **Capture.** The extracts stored here become the grounding corpus for
   external claims (`wizcore.facts.grounding`). Without them the gate rejects
   every timely post, correctly, because nothing substantiates the numbers.

Which is why capture and citation are the same act: you cannot cite what you did
not fetch, and fetching in order to satisfy the gate leaves the citation already
written.

Tavily rather than a scraper: it is already configured and working in the
Outreach agent, returns extracted text rather than HTML, and supports
`topic=news` with `time_range` — recency being the entire point here. One credit
per basic search.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from trends import store

log = logging.getLogger("content_poster.trends.verify")

_URL = "https://api.tavily.com/search"


def _publisher(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def search(config, query: str, timeout: int = 40) -> list[dict]:
    """One Tavily search. Returns normalised results; never raises."""
    if not config.tavily_api_key:
        return []
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                _URL,
                json={
                    "query": query[:380],
                    "topic": "news",
                    # A trend older than a week is not a trend. Narrowing here
                    # also stops Tavily returning a well-ranked 2023 article
                    # that would "corroborate" a 2026 claim.
                    "time_range": config.trend_time_range,
                    "search_depth": "basic",     # 1 credit; advanced costs 2
                    "max_results": config.trend_max_sources,
                    "include_raw_content": False,
                },
                headers={"Authorization": f"Bearer {config.tavily_api_key}"},
            )
        if resp.status_code != 200:
            log.warning("tavily HTTP %s: %s", resp.status_code, resp.text[:160])
            return []
        out = []
        for hit in resp.json().get("results", []):
            url = hit.get("url") or ""
            if not url:
                continue
            out.append({
                "url": url,
                "title": hit.get("title") or "",
                "publisher": _publisher(url),
                "extract": (hit.get("content") or "")[:4000],
                "relevance": hit.get("score"),
            })
        return out
    except Exception:
        log.warning("tavily search failed", exc_info=True)
        return []


def verify_item(config, item: dict, budget=None) -> tuple[bool, str, list[dict]]:
    """Corroborate one trend. Returns `(ok, reason, sources)`.

    The original item's own URL counts as one source, so a story that Tavily
    confirms once is already at two — which is the bar. Requiring two *Tavily*
    hits on top would reject genuinely real news that simply has not been
    aggregated yet.
    """
    if budget and not budget.afford("tavily", 1):
        return False, "tavily budget spent", []

    results = search(config, item["title"])
    if not results:
        return False, "no corroborating sources found", []

    # Distinct publishers, not distinct URLs. Three articles on one outlet is
    # one outlet, and treating it as three would defeat the whole check.
    publishers = {r["publisher"] for r in results if r["publisher"]}
    origin = _publisher(item.get("url") or "")
    if origin:
        publishers.add(origin)

    if len(publishers) < config.trend_min_sources:
        return False, (
            f"only {len(publishers)} distinct publisher(s), need "
            f"{config.trend_min_sources}"
        ), results

    return True, f"{len(publishers)} publishers", results


def run(config, budget=None, limit: int = 0) -> dict:
    """Verify the highest-scoring items and store their evidence."""
    from trends.score import scored_items

    counters = {"verified": 0, "unverified": 0, "sources_saved": 0}
    items = scored_items(config, limit or config.trend_verify_per_run)
    for item in items:
        ok, reason, sources = verify_item(config, item, budget)
        if not ok:
            store.mark(config, item["id"], "rejected", item.get("relevance"), reason)
            counters["unverified"] += 1
            continue
        counters["sources_saved"] += store.save_sources(config, item["id"], sources)
        store.mark(config, item["id"], "verified", item.get("relevance"), reason)
        counters["verified"] += 1

    log.info("trend verification: %s", counters)
    return counters
