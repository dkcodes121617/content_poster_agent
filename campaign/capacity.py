"""Capacity-driven scheduling and backfill — CONTENT_SYSTEM.md §5.

The ask was: when LinkedIn and Google Business Profile unlock, ramp volume hard
to catch up.

**The pushback, recorded here because the code implements it.** A brand-new
LinkedIn company page that starts posting five times a day is indistinguishable
from spam to both the algorithm and a human visitor, and early-page reach
penalties are sticky — they are not a slow week, they are a ceiling that stays.
The same is true of a GBP listing posting several times a day. What "catching
up" actually buys is consistency and archive depth, and those come from cadence
over weeks, not from a burst.

So this module does two things instead:

  **Ramp fast but bounded.** A platform enters at its launch rate and steps up
  weekly toward its steady rate, never past its hard ceiling. Enabling LinkedIn
  is one row in `content.posting_plan` and a deploy of nothing.

  **Backfill, which is the honest form of catching up.** A newly-enabled
  platform may republish the best already-validated posts of the last 30 days.
  Nobody on that platform has seen them, they are already proven, and
  `content.social_posts` already stores the captions — so an archive appears
  without a spam burst and without generating anything new.

The ceilings below are not advisory. They are the argument above, enforced.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from campaign.calendar import today_ist

log = logging.getLogger("content_poster.capacity")


@dataclass(frozen=True)
class PlatformPlan:
    platform: str
    launch: float        # posts/day on the first week a platform is live
    steady: float        # where the weekly step-up is heading
    ceiling: float       # never exceeded, whatever the plan table says
    step: float = 0.5    # added per week until steady is reached


# CONTENT_SYSTEM.md §5. Per-day rates; 3/week is 0.43/day.
DEFAULTS: dict[str, PlatformPlan] = {
    "linkedin":  PlatformPlan("linkedin", launch=1.0, steady=1.5, ceiling=2.0, step=0.25),
    "instagram": PlatformPlan("instagram", launch=0.43, steady=1.0, ceiling=1.0),
    "facebook":  PlatformPlan("facebook", launch=0.43, steady=1.0, ceiling=1.0),
    "threads":   PlatformPlan("threads", launch=0.71, steady=2.0, ceiling=3.0),
    "x":         PlatformPlan("x", launch=0.43, steady=2.0, ceiling=3.0),
    "gbp":       PlatformPlan("gbp", launch=0.29, steady=0.29, ceiling=1.0, step=0.0),
    "pinterest": PlatformPlan("pinterest", launch=0.29, steady=1.0, ceiling=3.0),
    "devto":     PlatformPlan("devto", launch=0.14, steady=0.29, ceiling=0.5, step=0.07),
}

BACKFILL_LOOKBACK_DAYS = 30


def ramp_schedule(platform: str, first_day: date, weeks: int = 8) -> list[tuple[date, float]]:
    """`(effective_from, target_per_day)` rows for a platform switching on.

    Written ahead of time rather than recomputed each run, so the ramp can be
    inspected — and corrected — before it happens instead of being discovered
    afterwards in the posting history.
    """
    plan = DEFAULTS.get(platform)
    if not plan:
        return []
    rows: list[tuple[date, float]] = []
    rate = plan.launch
    for week in range(weeks):
        rows.append((first_day + timedelta(days=7 * week), round(min(rate, plan.ceiling), 2)))
        if rate >= plan.steady or plan.step <= 0:
            continue
        rate = min(rate + plan.step, plan.steady)
    # Collapse the tail: once the rate stops changing, more rows say nothing.
    trimmed: list[tuple[date, float]] = []
    for row in rows:
        if trimmed and trimmed[-1][1] == row[1]:
            continue
        trimmed.append(row)
    return trimmed


def write_ramp(config, platform: str, first_day: date | None = None, weeks: int = 8) -> int:
    """Persist a ramp. Idempotent — re-running writes nothing new."""
    from wizcore.db.conn import connect

    rows = ramp_schedule(platform, first_day or today_ist(), weeks)
    if not rows:
        log.warning("no ramp defaults for platform %r", platform)
        return 0
    plan = DEFAULTS[platform]
    written = 0
    with connect(config.database_url) as conn, conn.cursor() as cur:
        for effective_from, target in rows:
            cur.execute(
                "INSERT INTO content.posting_plan "
                "(platform, target_per_day, hard_ceiling, effective_from, note) "
                "VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT (platform, effective_from) DO NOTHING",
                (platform, target, plan.ceiling, effective_from,
                 f"bounded ramp toward {plan.steady}/day"),
            )
            written += cur.rowcount
    return written


def target_for(config, platform: str, today: date | None = None) -> float:
    """Posts per day for this platform right now.

    Falls back to the launch rate when there is no plan row and no database.
    Never returns more than the ceiling even if a row says otherwise — a typo in
    a table must not be able to publish five times a day to a two-week-old page.
    """
    from wizcore.db.conn import connect

    plan = DEFAULTS.get(platform)
    ceiling = plan.ceiling if plan else 1.0
    fallback = plan.launch if plan else 0.43
    try:
        with connect(config.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT target_per_day, hard_ceiling FROM content.posting_plan "
                "WHERE platform = %s AND effective_from <= %s "
                "ORDER BY effective_from DESC LIMIT 1",
                (platform, today or today_ist()),
            )
            row = cur.fetchone()
    except Exception:
        log.warning("posting plan unavailable for %s; using launch rate", platform, exc_info=True)
        return fallback
    if not row:
        return fallback
    return min(float(row["target_per_day"]), float(row["hard_ceiling"]), ceiling)


def posted_today(config, platform: str, today: date | None = None) -> int:
    from wizcore.db.conn import connect

    try:
        with connect(config.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM content.social_posts "
                "WHERE platform = %s AND status = 'published' "
                "AND created_at::date = %s",
                (platform, today or today_ist()),
            )
            return int((cur.fetchone() or {}).get("n", 0))
    except Exception:
        # Unknown is treated as zero, and that is the wrong-but-safe direction
        # only because `core.external_actions` is what actually prevents a
        # double post. This number governs pacing, not correctness.
        log.warning("could not count today's posts for %s", platform, exc_info=True)
        return 0


def has_capacity(config, platform: str, today: date | None = None) -> bool:
    """Whether another post today would stay inside the plan."""
    target = target_for(config, platform, today)
    if target <= 0:
        return False
    # A sub-1 target means "some days, not every day". Rounding up would make
    # 3/week behave as 7/week; the calendar already decides *which* days, so
    # this only has to cap the busy ones.
    allowed = max(1, int(target)) if target >= 1 else 1
    return posted_today(config, platform, today) < allowed


# ── backfill ─────────────────────────────────────────────────────────────────
def backfill_candidates(config, platform: str, limit: int = 3) -> list[dict]:
    """Already-published posts this platform has never seen.

    Three conditions, and each one is doing work:

      * published, not failed - only proven copy gets reused
      * from a DIFFERENT platform - reposting to where it already ran is
        duplication, not catch-up
      * never backfilled here before - `content.backfill_log` has a unique
        constraint, so this is belt and braces on a real guarantee

    Newest first, because a thirty-day-old take on the news is not evergreen and
    the caller filters `timely` out anyway.
    """
    from wizcore.db.conn import connect

    try:
        with connect(config.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT p.id, p.platform AS origin, p.pillar, p.caption, p.image_urls, "
                "       p.created_at "
                "FROM content.social_posts p "
                "WHERE p.status = 'published' "
                "  AND p.platform <> %s "
                "  AND p.pillar <> 'timely' "
                "  AND p.created_at > now() - make_interval(days => %s) "
                "  AND NOT EXISTS (SELECT 1 FROM content.backfill_log b "
                "                  WHERE b.source_post_id = p.id AND b.platform = %s) "
                "ORDER BY p.created_at DESC LIMIT %s",
                (platform, BACKFILL_LOOKBACK_DAYS, platform, limit),
            )
            return list(cur.fetchall())
    except Exception:
        log.warning("backfill candidates unavailable for %s", platform, exc_info=True)
        return []


def record_backfill(config, source_post_id: int, platform: str) -> None:
    from wizcore.db.conn import connect

    try:
        with connect(config.database_url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO content.backfill_log (source_post_id, platform) "
                "VALUES (%s,%s) ON CONFLICT DO NOTHING",
                (source_post_id, platform),
            )
    except Exception:
        log.warning("could not record backfill", exc_info=True)


def describe(config, platforms: list[str], today: date | None = None) -> list[str]:
    """One line per platform, for `--schedule` and the digest."""
    out = []
    for platform in platforms:
        target = target_for(config, platform, today)
        plan = DEFAULTS.get(platform)
        ceiling = f"/{plan.ceiling:g} ceiling" if plan else ""
        out.append(
            f"  {platform:<10} {target:g}/day{ceiling}"
            f"  ({posted_today(config, platform, today)} today)"
        )
    return out
