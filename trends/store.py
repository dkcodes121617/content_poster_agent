"""Persistence and clustering for trend items.

## Why clustering matters more than deduplication

`UNIQUE (source, external_id)` stops the same HN post entering twice. It does
nothing about the same *story* arriving as an HN thread, a Reddit discussion,
two news headlines and a dev.to write-up — five rows, one event. Without
clustering that story gets scored five times, and posted about more than once.

The cluster key is a normalised title signature: lowercase, stopwords removed,
the most distinctive words sorted. Crude compared to embeddings, and chosen
deliberately — the alternative is `sentence-transformers`, which drags PyTorch
into an image that already carries Chromium, for a job that compares a few
hundred short headlines a day.

It is also the **velocity** signal, which is the part worth having: a story in
one source is noise, the same story in four sources within six hours is a trend.
One mechanism, two uses.
"""
from __future__ import annotations

import json
import logging
import re

from wizcore.db.conn import connect, fetch_all

log = logging.getLogger("content_poster.trends.store")

# Words that carry no distinguishing signal in a headline.
_STOP = frozenset(["a", "an", "the", "and", "or", "but", "if", "then", "than", "that", "this", "these", "those", "is", "are", "was", "were", "be", "been", "being", "to", "of", "in", "on", "at", "by", "for", "with", "from", "as", "it", "its", "it's", "you", "your", "we", "our", "they", "their", "he", "she", "his", "her", "i", "me", "my", "new", "now", "how", "why", "what", "when", "where", "who", "which", "will", "would", "can", "could", "should", "may", "might", "just", "also", "more", "most", "very", "much", "some", "any", "no", "not", "says", "said", "after", "before", "over", "under", "about", "into", "out", "up", "down", "off", "again", "once", "here", "there", "all"])

_WORD = re.compile(r"[a-z0-9][a-z0-9'+.-]*")


def cluster_key(title: str, keep: int = 5) -> str:
    """A stable signature for "the same story".

    Sorted rather than positional, so "OpenAI ships Codex" and "Codex shipped by
    OpenAI" collapse to one key. Capped at `keep` words: longer keys are more
    precise and cluster almost nothing, which defeats the purpose.
    """
    words = [w for w in _WORD.findall((title or "").lower()) if w not in _STOP and len(w) > 2]
    if not words:
        return ""
    # Longest words first: they carry the most signal (product and company names
    # are long, verbs are short). Then sorted, so word order cannot matter.
    distinctive = sorted(sorted(words, key=len, reverse=True)[:keep])
    return "-".join(distinctive)


def save_items(config, items: list, source_override: str = "") -> dict:
    """Insert harvested items. Returns counters. Never raises.

    `ON CONFLICT DO NOTHING` on `(source, external_id)` makes re-harvesting a
    no-op, so overlapping schedules and retries are free.
    """
    counters = {"seen": len(items), "inserted": 0, "duplicate": 0}
    if not items:
        return counters
    try:
        with connect(config.database_url) as conn, conn.cursor() as cur:
            for item in items:
                key = cluster_key(item.title)
                cur.execute(
                    """
                    INSERT INTO content.trend_items
                        (source, external_id, title, url, summary, author,
                         signals, published_at, cluster_key, raw)
                    VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s::jsonb)
                    ON CONFLICT (source, external_id) DO NOTHING
                    RETURNING id
                    """,
                    (
                        source_override or item.source,
                        item.external_id[:200],
                        item.title[:500],
                        item.url or None,
                        (item.summary or "")[:2000] or None,
                        (item.author or "")[:200] or None,
                        json.dumps(item.signals or {}),
                        item.published_at,
                        key or None,
                        json.dumps(item.raw or {}, default=str),
                    ),
                )
                if cur.fetchone():
                    counters["inserted"] += 1
                else:
                    counters["duplicate"] += 1
    except Exception:
        log.error("could not save trend items", exc_info=True)
    return counters


def unscored(config, limit: int = 120, max_age_hours: int = 36) -> list[dict]:
    """New items worth scoring, newest first.

    Age-bounded: an item that has sat unscored for a day and a half is not going
    to become timely, and scoring it spends budget to produce a stale angle.
    """
    try:
        with connect(config.database_url, autocommit=True) as conn:
            return fetch_all(
                conn,
                "SELECT id, source, external_id, title, url, summary, signals, "
                "       published_at, surfaced_at, cluster_key "
                "FROM content.trend_items "
                "WHERE status = 'new' "
                "  AND surfaced_at > now() - make_interval(hours => %s) "
                "ORDER BY surfaced_at DESC LIMIT %s",
                (max_age_hours, limit),
            )
    except Exception:
        log.error("could not read unscored trends", exc_info=True)
        return []


def cluster_sizes(config, keys: list[str], hours: int = 24) -> dict[str, int]:
    """How many distinct SOURCES carry each story — the velocity signal.

    Distinct sources, not row count: five Google News headlines about one launch
    is one outlet syndicating itself, while HN + Reddit + news + dev.to is an
    actual trend. Counting rows would rank the syndication higher.
    """
    if not keys:
        return {}
    try:
        with connect(config.database_url, autocommit=True) as conn:
            rows = fetch_all(
                conn,
                "SELECT cluster_key, count(DISTINCT source) AS n "
                "FROM content.trend_items "
                "WHERE cluster_key = ANY(%s) "
                "  AND surfaced_at > now() - make_interval(hours => %s) "
                "GROUP BY cluster_key",
                (keys, hours),
            )
        return {r["cluster_key"]: int(r["n"]) for r in rows}
    except Exception:
        return {}


def already_covered(config, keys: list[str], days: int = 14) -> set[str]:
    """Cluster keys we have already published an angle about.

    Posting the same story twice a fortnight apart is the failure this prevents,
    and it is invisible without a memory: each run sees a fresh-looking item.
    """
    if not keys:
        return set()
    try:
        with connect(config.database_url, autocommit=True) as conn:
            rows = fetch_all(
                conn,
                "SELECT DISTINCT i.cluster_key FROM content.trend_angles a "
                "JOIN content.trend_items i ON i.id = a.trend_id "
                "WHERE i.cluster_key = ANY(%s) AND a.status = 'used' "
                "  AND a.used_at > now() - make_interval(days => %s)",
                (keys, days),
            )
        return {r["cluster_key"] for r in rows if r["cluster_key"]}
    except Exception:
        return set()


def mark(config, item_id: int, status: str, relevance: int | None = None,
         reason: str = "") -> None:
    try:
        with connect(config.database_url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE content.trend_items SET status = %s, relevance = %s, "
                "reject_reason = %s WHERE id = %s",
                (status, relevance, reason[:400] or None, item_id),
            )
    except Exception:
        log.warning("could not mark trend %s as %s", item_id, status, exc_info=True)


def save_sources(config, trend_id: int, sources: list[dict]) -> int:
    """Store captured evidence. This is the grounding corpus for external claims."""
    if not sources:
        return 0
    saved = 0
    try:
        with connect(config.database_url) as conn, conn.cursor() as cur:
            for source in sources:
                cur.execute(
                    "INSERT INTO content.trend_sources "
                    "(trend_id, url, title, publisher, extract, published_at, relevance) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (trend_id, url) DO NOTHING",
                    (
                        trend_id,
                        source["url"][:1000],
                        (source.get("title") or "")[:400] or None,
                        (source.get("publisher") or "")[:200] or None,
                        (source.get("extract") or "")[:8000],
                        source.get("published_at"),
                        source.get("relevance"),
                    ),
                )
                saved += cur.rowcount
    except Exception:
        log.error("could not save trend sources", exc_info=True)
    return saved


def sources_for(config, trend_id: int) -> list[dict]:
    try:
        with connect(config.database_url, autocommit=True) as conn:
            return fetch_all(
                conn,
                "SELECT url, title, publisher, extract, retrieved_at, published_at "
                "FROM content.trend_sources WHERE trend_id = %s ORDER BY id",
                (trend_id,),
            )
    except Exception:
        return []


def purge(config, item_days: int = 21) -> dict:
    """Retention. Sources referenced by an angle are never deleted.

    A published post's citation has to still resolve months later, so the sweep
    drops raw items and expired angles but leaves the evidence behind them.
    """
    counters = {"items_purged": 0, "angles_expired": 0}
    try:
        with connect(config.database_url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE content.trend_angles SET status = 'expired' "
                "WHERE status = 'ready' AND expires_at < now()"
            )
            counters["angles_expired"] = cur.rowcount
            cur.execute(
                "DELETE FROM content.trend_items "
                "WHERE surfaced_at < now() - make_interval(days => %s) "
                "  AND id NOT IN (SELECT trend_id FROM content.trend_angles "
                "                 WHERE trend_id IS NOT NULL)",
                (item_days,),
            )
            counters["items_purged"] = cur.rowcount
    except Exception:
        log.warning("trend purge failed", exc_info=True)
    return counters
