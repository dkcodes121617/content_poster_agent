"""The daily "still broken" list — the one place a silent failure becomes a sentence.

Every agent here alerts on CHANGE, deliberately: a source that starts failing
says so once, a run that crashes says so once, and then they go quiet so the
channel stays readable. That rule fixed the 1,400-messages-in-three-weeks flood,
and it also made one missed message permanent silence. Measured on 4 Oct:

  * Reddit had been dead for five weeks (vendor credits, HTTP 402). Its single
    "top up" alert fired once, on 13 Sep.
  * Outreach crashed on every send attempt for two weeks and had never sent an
    email at all.
  * The blog agent had published nothing for a week while its workflow showed
    green, because aborting cleanly counts as success.

None of those were visible without going to look. So this module restates,
once a day in the midnight brief, every problem that is STILL true — and says
nothing when there is nothing. A daily line about the same broken thing is the
point: it is a reminder that something is costing leads today, not news.

Read-only, and it never raises: a health check that can crash the brief is a
health check that hides the brief.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta

from wizcore.db.conn import connect

from campaign.calendar import today_ist

log = logging.getLogger("content_poster.health")

# How long each agent may go without starting a run before its scheduler is
# presumed stopped. Content Poster and Lead Finder tick every 30 minutes.
# Outreach runs 07:00 and 09:00 UTC on weekdays only ("0 7,9 * * 1-5"), so its
# longest normal gap is Friday 09:00 -> Monday 07:00 = 70h; anything under that
# is a weekend, not an outage.
_STALE_AFTER = {
    "content_poster": timedelta(hours=3),
    "lead_finder": timedelta(hours=3),
    "outreach": timedelta(hours=74),
}
# Two or more failed/aborted runs in a day is a pattern, one is weather.
_FAILED_RUNS_THRESHOLD = 2
# The blog agent aims for more than one post a day; three days with none means
# it is stuck, not resting.
_BLOG_STALE_DAYS = 3
_CREDENTIAL_WARN_DAYS = 7

# Python's exception line: an optionally dotted name, then ": message" or the end.
# The name must be CamelCase or end in Error/Exception/Exit, which keeps out
# Postgres' all-caps "CONTEXT:" / "DETAIL:" lines and LangGraph's "During task"
# trailer - and still catches psycopg.errors.FeatureNotSupported, OSError, etc.
_EXC_LINE = re.compile(
    r"^(?:[A-Za-z_]\w*\.)*(?:[A-Z][a-z]\w*|\w*(?:Error|Exception|Exit))(?::\s|$)"
)


def check(config, snapshot=None, now: datetime | None = None) -> list[str]:
    """Plain-text lines, one per problem still true right now. Empty means healthy.

    `snapshot` (a wizcore FactsSnapshot) lets the blog check read the site's own
    post registry; without it the dev.to syndication log stands in, which lags
    by at most one Content Poster tick. `now`, when given, must be timezone-aware.
    """
    today = now.date() if now else today_ist(getattr(config, "display_tz", "Asia/Kolkata"))
    lines: list[str] = []
    try:
        with connect(config.database_url) as conn, conn.cursor() as cur:
            lines += _runs(cur, now)
            lines += _sources(cur)
            lines += _outreach(cur)
            lines += _credentials(cur)
            if snapshot is None:
                lines += _blog_from_syndication(cur, today)
    except Exception:
        log.warning("health check could not read the database", exc_info=True)
        lines.append("Health check could not read the database - status unknown.")
    if snapshot is not None:
        lines += _blog_from_snapshot(snapshot, today)
    return lines


def _runs(cur, now: datetime | None) -> list[str]:
    cur.execute(
        """
        SELECT agent,
               max(started_at) AS last_run,
               count(*) FILTER (
                   WHERE status IN ('failed', 'aborted')
                     AND started_at > now() - interval '24 hours') AS bad_24h,
               (array_agg(error ORDER BY started_at DESC) FILTER (
                   WHERE status IN ('failed', 'aborted')
                     AND started_at > now() - interval '24 hours'))[1] AS last_error,
               now() AS db_now
          FROM core.agent_runs
         WHERE started_at > now() - interval '14 days'
         GROUP BY agent
        """
    )
    out: list[str] = []
    for row in cur.fetchall():
        agent = row["agent"]
        db_now = now or row["db_now"]
        stale_after = _STALE_AFTER.get(agent)
        if stale_after and row["last_run"] and db_now - row["last_run"] > stale_after:
            hours = int((db_now - row["last_run"]).total_seconds() // 3600)
            out.append(f"⏸ {agent}: no run for {hours}h - its schedule may have stopped.")
        if (row["bad_24h"] or 0) >= _FAILED_RUNS_THRESHOLD:
            out.append(
                f"❌ {agent}: {row['bad_24h']} failed runs in 24h - "
                f"{error_summary(row['last_error'] or '')}"
            )
    return out


def _sources(cur) -> list[str]:
    # Only sources attempted in the last two days. The Lead Finder re-probes a
    # muted source every few hours, so anything enabled and failing is always
    # recent here, while a source somebody switched off goes stale and drops out
    # instead of being reported forever.
    cur.execute(
        "SELECT source, last_error, fail_streak FROM leadfind.source_cursors "
        "WHERE NOT last_ok AND last_run_at > now() - interval '2 days' ORDER BY source"
    )
    out: list[str] = []
    for row in cur.fetchall():
        error = (row["last_error"] or "").strip()
        hint = ""
        if "402" in error or "credit" in error.lower():
            hint = " - 💳 out of vendor credits, top up to restore it"
        out.append(
            f"🔌 lead source {row['source']} failing ({row['fail_streak']} in a row): "
            f"{error[:110]}{hint}"
        )
    return out


def _outreach(cur) -> list[str]:
    cur.execute(
        """
        SELECT
          (SELECT count(*) FROM core.agent_runs
            WHERE agent = 'outreach' AND started_at > now() - interval '7 days') AS runs,
          (SELECT count(*) FROM core.outreach_log
            WHERE channel = 'email' AND status = 'sent'
              AND sent_at > now() - interval '7 days') AS sent
        """
    )
    row = cur.fetchone() or {}
    if (row.get("runs") or 0) and not (row.get("sent") or 0):
        return ["📭 Outreach sent 0 emails in the last 7 days - outbound is not running."]
    return []


def _credentials(cur) -> list[str]:
    cur.execute(
        "SELECT name, expires_at, last_error FROM core.agent_credentials "
        "WHERE (expires_at IS NOT NULL AND expires_at < now() + make_interval(days => %s)) "
        "   OR coalesce(last_error, '') <> '' ORDER BY name",
        (_CREDENTIAL_WARN_DAYS,),
    )
    out: list[str] = []
    for row in cur.fetchall():
        if row.get("last_error"):
            out.append(f"🔑 {row['name']}: refresh failing - {row['last_error'][:110]}")
        elif row.get("expires_at"):
            out.append(f"🔑 {row['name']} expires {row['expires_at']:%d %b} - refresh it.")
    return out


def _blog_from_snapshot(snapshot, today: date) -> list[str]:
    posts = list(getattr(snapshot, "existing_posts", None) or [])
    dates = sorted((p.get("date") or "") for p in posts if p.get("date"))
    if not dates:
        return []
    try:
        newest = date.fromisoformat(dates[-1][:10])
    except ValueError:
        return []
    return _blog_line(newest, today)


def _blog_from_syndication(cur, today: date) -> list[str]:
    cur.execute(
        "SELECT max(promoted_at) AS newest FROM content.promoted_assets WHERE asset_type = 'blog'"
    )
    row = cur.fetchone() or {}
    if not row.get("newest"):
        return []
    return _blog_line(row["newest"].date(), today)


def _blog_line(newest: date, today: date) -> list[str]:
    days = (today - newest).days
    if days > _BLOG_STALE_DAYS:
        return [f"📝 blog: no new post for {days} days (last {newest:%d %b}) - the blog agent is stuck."]
    return []


def error_summary(error: str) -> str:
    """The exception line of a stored traceback, not its first frame.

    `core.agent_runs.error` holds whole tracebacks, and LangGraph appends a
    "During task with name ..." trailer, so neither the first nor the last line
    says what went wrong. The line that does is the one naming the exception.
    """
    lines = [ln.strip() for ln in (error or "").splitlines() if ln.strip()]
    for line in reversed(lines):
        if _EXC_LINE.match(line):
            return line[:160]
    return (lines[-1] if lines else "no error recorded")[:160]
