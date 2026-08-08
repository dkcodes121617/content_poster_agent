"""Trend harvesting — free, keyless, no browser.

Every source here returns JSON or RSS. That is the whole reason there is no
Playwright in this file: the browser stack was removed from the Outreach agent
for good reasons (400 MB in the image, two-minute cold starts, a renderer whose
failure mode is *silent*), and nothing a trend layer needs is JS-gated.

Chromium is present in this agent's image for slide rendering, so if a source
ever genuinely requires a browser it costs nothing to add one. Building on it by
default would mean paying that cost on every run for a capability almost nothing
needs.

## What is NOT here

Hacker News, Reddit, X and Stack Exchange. The Lead Finder already fetches all
four every 30 minutes and discards whatever is not a lead — see
`trends/piggyback.py`. Re-fetching them here would double the spend on two
metered vendors to obtain bytes we already had.
"""
from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from xml.etree import ElementTree

import httpx

log = logging.getLogger("content_poster.trends.harvest")

_UA = {"user-agent": "wizcodes-trends/1.0 (+https://wizcodes.site)"}


@dataclass
class TrendItem:
    source: str
    external_id: str
    title: str
    url: str = ""
    summary: str = ""
    author: str = ""
    signals: dict = field(default_factory=dict)
    published_at: datetime | None = None
    raw: dict = field(default_factory=dict)


def harvest_all(config, timeout: int = 25) -> tuple[list[TrendItem], list[str]]:
    """Run every free source. Returns `(items, errors)`; never raises.

    One dead source must not cost the others, so each is wrapped
    independently — the same rule the Lead Finder's fan-out follows.
    """
    items: list[TrendItem] = []
    errors: list[str] = []
    for name, fn in (
        ("github", github_trending),
        ("news", google_news),
        ("devto", devto_top),
        ("hackernews", hn_front_page),
    ):
        try:
            found = fn(config, timeout)
            items.extend(found)
            log.info("harvest %s: %d item(s)", name, len(found))
        except Exception as e:
            errors.append(f"{name}: {e}")
            log.warning("harvest %s failed", name, exc_info=True)
    return items, errors


# ── GitHub: new repos gaining stars fast ───────────────────────────────────
def github_trending(config, timeout: int = 25) -> list[TrendItem]:
    """Repos created recently that are already gaining stars.

    GitHub has no official "trending" API, but search with a `created:` filter
    sorted by stars is a better signal anyway: it finds things that got popular
    *fast*, rather than things that are merely popular.

    Unauthenticated search allows 10 requests/minute, which is ample for one
    call every few hours. A token would raise that and is not needed.
    """
    since = (datetime.now(UTC) - timedelta(days=config.trend_github_days)).date().isoformat()
    out: list[TrendItem] = []
    with httpx.Client(timeout=timeout, headers={**_UA, "Accept": "application/vnd.github+json"}) as c:
        resp = c.get(
            "https://api.github.com/search/repositories",
            params={
                "q": f"created:>{since} stars:>{config.trend_github_min_stars}",
                "sort": "stars",
                "order": "desc",
                "per_page": 20,
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code} {resp.text[:120]}")
        for repo in resp.json().get("items", []):
            out.append(
                TrendItem(
                    source="github",
                    external_id=str(repo["id"]),
                    title=f"{repo['full_name']} - {repo.get('description') or ''}".strip(" -"),
                    url=repo.get("html_url", ""),
                    summary=repo.get("description") or "",
                    author=(repo.get("owner") or {}).get("login", ""),
                    signals={
                        "stars": repo.get("stargazers_count", 0),
                        "forks": repo.get("forks_count", 0),
                        "language": repo.get("language"),
                    },
                    published_at=_iso(repo.get("created_at")),
                    raw={"topics": repo.get("topics", [])},
                )
            )
    return out


# ── Google News RSS: headlines, no key ─────────────────────────────────────
def google_news(config, timeout: int = 25) -> list[TrendItem]:
    """Headlines per configured query. Free, keyless, and genuinely broad.

    RSS rather than a search API because it needs no credential and no quota.
    The trade is no relevance score and no full text — both of which the
    verification step supplies later via Tavily, and only for the few items that
    survive scoring.
    """
    out: list[TrendItem] = []
    with httpx.Client(timeout=timeout, headers=_UA, follow_redirects=True) as client:
        for query in config.trend_news_queries:
            url = (
                "https://news.google.com/rss/search"
                f"?q={httpx.QueryParams({'q': query})['q']}"
                "&hl=en-US&gl=US&ceid=US:en"
            )
            resp = client.get(url)
            if resp.status_code != 200:
                log.warning("google news %r -> HTTP %s", query, resp.status_code)
                continue
            # Capped per query. Google News returns ~100 items per feed, and
            # five queries produced 487 rows in one harvest — far more than the
            # scorer's batch, so the surplus would simply age out unscored while
            # crowding better sources out of the batch. The feed is ordered by
            # relevance, so the head is the part worth keeping.
            out.extend(_parse_rss(resp.text, "news", query)[: config.trend_news_per_query])
    return out


def _parse_rss(xml_text: str, source: str, query: str) -> list[TrendItem]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as e:
        log.warning("unparseable RSS for %r: %s", query, e)
        return []
    out: list[TrendItem] = []
    for item in root.findall(".//item"):
        title = _text(item, "title")
        link = _text(item, "link")
        if not (title and link):
            continue
        out.append(
            TrendItem(
                source=source,
                # Google's guid is stable per story; the link carries tracking
                # junk that changes between fetches and would defeat dedup.
                external_id=_text(item, "guid") or link,
                title=_clean(title),
                url=link,
                summary=_clean(_text(item, "description"))[:600],
                author=_text(item, "source"),
                published_at=_rfc822(_text(item, "pubDate")),
                raw={"query": query},
            )
        )
    return out


# ── dev.to: what developers are actually reading ───────────────────────────
def devto_top(config, timeout: int = 25) -> list[TrendItem]:
    out: list[TrendItem] = []
    with httpx.Client(timeout=timeout, headers=_UA) as client:
        resp = client.get(
            "https://dev.to/api/articles",
            params={"top": config.trend_devto_days, "per_page": 20},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}")
        for article in resp.json():
            out.append(
                TrendItem(
                    source="devto",
                    external_id=str(article.get("id")),
                    title=article.get("title", ""),
                    url=article.get("url", ""),
                    summary=article.get("description", "") or "",
                    author=(article.get("user") or {}).get("name", ""),
                    signals={
                        "reactions": article.get("public_reactions_count", 0),
                        "comments": article.get("comments_count", 0),
                    },
                    published_at=_iso(article.get("published_at")),
                    raw={"tags": article.get("tag_list", [])},
                )
            )
    return out


# ── Hacker News front page ─────────────────────────────────────────────────
def hn_front_page(config, timeout: int = 25) -> list[TrendItem]:
    """The front page itself, which the Lead Finder never looks at.

    The Lead Finder queries HN for buyer-intent phrases; this wants whatever is
    simply *big* today. Different query, same free API, so it is worth the one
    extra call the piggyback cannot provide.
    """
    out: list[TrendItem] = []
    with httpx.Client(timeout=timeout, headers=_UA) as client:
        resp = client.get(
            "https://hn.algolia.com/api/v1/search",
            params={
                "tags": "front_page",
                "hitsPerPage": 30,
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}")
        for hit in resp.json().get("hits", []):
            if int(hit.get("points") or 0) < config.trend_hn_min_points:
                continue
            out.append(
                TrendItem(
                    source="hackernews",
                    external_id=str(hit.get("objectID")),
                    title=hit.get("title") or "",
                    url=hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                    summary=_clean(hit.get("story_text") or "")[:600],
                    author=hit.get("author", ""),
                    signals={
                        "points": hit.get("points", 0),
                        "comments": hit.get("num_comments", 0),
                    },
                    published_at=_iso(hit.get("created_at")),
                )
            )
    return out


# ── helpers ────────────────────────────────────────────────────────────────
def _text(node, tag: str) -> str:
    found = node.find(tag)
    return (found.text or "").strip() if found is not None and found.text else ""


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def _iso(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _rfc822(value: str) -> datetime | None:
    if not value:
        return None
    from email.utils import parsedate_to_datetime

    try:
        parsed = parsedate_to_datetime(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None
