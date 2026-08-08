"""The trend pipeline, end to end.

    harvest -> score -> verify -> angle -> purge

Split into two entry points because the stages have different costs and
different useful frequencies:

  `harvest_only()`  free APIs, no LLM. Cheap enough to run hourly.
  `refine()`        Groq scoring, Tavily verification, proxy synthesis.
                    Twice a day, on whatever accumulated.

Separating them means a spike in trend volume costs HTTP requests, not LLM
budget — and the expensive model only ever sees the handful of items that
already cleared every free gate.
"""
from __future__ import annotations

import logging

from wizcore.obs.log import log_event

from trends import angle, harvest, score, store, verify

log = logging.getLogger("content_poster.trends.run")


def harvest_only(config) -> dict:
    """Fetch from the free sources and store. No LLM, no metered vendor."""
    if not config.trends_enabled:
        return {"skipped": "TRENDS_ENABLED=0"}
    items, errors = harvest.harvest_all(config)
    counters = store.save_items(config, items)
    counters["sources_failed"] = len(errors)
    if errors:
        counters["errors"] = "; ".join(errors[:3])
    log_event(log, "trends.harvest", **{k: v for k, v in counters.items() if isinstance(v, int)})
    return counters


def refine(config, budget=None) -> dict:
    """Score, verify and synthesise. The stages that cost money."""
    if not config.trends_enabled:
        return {"skipped": "TRENDS_ENABLED=0"}
    counters: dict = {}
    counters.update(score.run(config, budget))
    counters.update(verify.run(config, budget))
    counters.update(angle.run(config, budget))
    counters.update(store.purge(config, config.trend_item_retention_days))
    log_event(log, "trends.refine", **{k: v for k, v in counters.items() if isinstance(v, int)})
    return counters


def full(config, budget=None) -> dict:
    counters = harvest_only(config)
    counters.update(refine(config, budget))
    return counters


def summary(config) -> str:
    """A human-readable state of the funnel, for `--trends` and the digest.

    The reject counts are the point. If the gate rejects everything for a week
    it is too tight; if it rejects nothing it is too loose. Neither is visible
    without printing them.
    """
    from wizcore.db.conn import connect, fetch_all

    lines = ["Trend funnel (7 days)"]
    try:
        with connect(config.database_url, autocommit=True) as conn:
            rows = fetch_all(
                conn,
                "SELECT status, count(*) AS n FROM content.trend_items "
                "WHERE surfaced_at > now() - interval '7 days' "
                "GROUP BY status ORDER BY n DESC",
            )
            for row in rows:
                lines.append(f"  {row['status']:<10} {row['n']}")

            rejects = fetch_all(
                conn,
                "SELECT reject_reason, count(*) AS n FROM content.trend_items "
                "WHERE status = 'rejected' AND reject_reason IS NOT NULL "
                "  AND surfaced_at > now() - interval '7 days' "
                "GROUP BY reject_reason ORDER BY n DESC LIMIT 6",
            )
            if rejects:
                lines.append("\nTop reject reasons")
                for row in rejects:
                    lines.append(f"  {row['n']:>3}  {row['reject_reason'][:90]}")

            ready = fetch_all(
                conn,
                "SELECT a.headline, a.service_line, a.expires_at, i.relevance "
                "FROM content.trend_angles a JOIN content.trend_items i ON i.id = a.trend_id "
                "WHERE a.status = 'ready' AND a.expires_at > now() "
                "ORDER BY i.relevance DESC LIMIT 5",
            )
            lines.append("\nReady to post" if ready else "\nNo angles ready")
            for row in ready:
                lines.append(
                    f"  [{row['relevance']}] {row['headline'][:78]}"
                    f"  ({row['service_line']})"
                )
    except Exception as e:
        lines.append(f"  could not read: {e}")
    return "\n".join(lines)
