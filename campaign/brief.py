"""The 00:00 IST daily brief.

One message at the start of each Indian day answering three questions, in the
order they matter:

  1. **What happened yesterday** — every post that went out, with its link, and
     anything that was rejected and why.
  2. **What is planned today** — every slot, with its time, platform, pillar and
     the region it is written for.
  3. **What needs your hands** — X and YouTube drafts waiting in the queue, so
     the day starts with the manual work visible rather than discovered.

## Why a brief and not just the per-post notifications

The per-post messages already exist and they are the wrong shape for this. They
arrive one at a time across sixteen hours, they say nothing about what is
*coming*, and a run that publishes nothing sends nothing at all — so a day where
the agent quietly did no work looks identical to a day you were not watching.
The brief always arrives, and "0 posts due today" is information.

It also runs at midnight rather than in the morning on purpose: the calendar's
first slot is 11:00 IST, so a midnight brief is the only version where the plan
arrives before the work does.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date, timedelta

from wizcore.telegram.send import esc

from campaign import phase, regions
from campaign.calendar import WEEK, boost_active, today_ist

log = logging.getLogger("content_poster.brief")

_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def compose(config, today: date | None = None) -> str:
    """The whole message. Never raises — a brief that fails is not a run that fails."""
    today = today or today_ist(config.display_tz)
    parts = [
        f"🌅 <b>{_DAYS[today.weekday()]} {today:%d %b %Y}</b>",
        _phase_line(config, today),
        "",
        _health_section(config),
        _yesterday(config, today),
        "",
        _plan(config, today),
        "",
        _manual(config),
        _trends(config),
    ]
    return "\n".join(p for p in parts if p is not None)


# ── the header ───────────────────────────────────────────────────────────────
def _phase_line(config, today: date) -> str:
    start = config.start_date()
    current = phase.current(start, today)
    bits = [f"phase <b>{esc(current.name)}</b>"]
    if start:
        bits.append(f"week {phase.week_of(start, today)}")
    if boost_active(start, config.boost_weeks, today):
        left = (start + timedelta(weeks=config.boost_weeks) - today).days
        bits.append(f"🚀 launch boost, {left} day(s) left")
    if config.dry_run:
        bits.append("🧪 <b>DRY RUN</b> - nothing is actually published")
    return " · ".join(bits)


# ── 0. what is still broken ──────────────────────────────────────────────────
def _health_lines(config) -> list[str]:
    """Problems still true right now, across all three agents. Never raises."""
    from campaign import health

    snapshot = None
    try:
        from wizcore.facts.site import SiteReader
        from wizcore.facts.snapshot import build_snapshot

        snapshot = build_snapshot(SiteReader(
            repo=config.site_repo, token=config.site_read_token,
            ref=config.site_branch, local_dir=config.site_local_dir or None,
        ))
    except Exception:
        # The blog line falls back to the dev.to syndication log.
        log.warning("could not read the site for the health check", exc_info=True)
    try:
        return health.check(config, snapshot)
    except Exception:
        log.warning("health check failed", exc_info=True)
        return []


def _health_section(config) -> str | None:
    lines = _health_lines(config)
    if not lines:
        return None
    return "\n".join(["🚨 <b>Needs attention</b>", *(f"  {esc(x)}" for x in lines), ""])


# ── 1. yesterday ─────────────────────────────────────────────────────────────
def _yesterday(config, today: date) -> str:
    """What actually went out, with links. The part that is checkable."""
    from wizcore.db.conn import connect

    day = today - timedelta(days=1)
    try:
        with connect(config.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT platform, pillar, status, permalink, error "
                "FROM content.social_posts "
                "WHERE published_at::date = %s ORDER BY published_at",
                (day,),
            )
            rows = list(cur.fetchall())
    except Exception:
        log.warning("could not read yesterday's posts", exc_info=True)
        return "📤 <b>Yesterday</b>\n  (post history unavailable)"

    if not rows:
        return f"📤 <b>Yesterday ({day:%d %b})</b>\n  nothing published"

    lines = [f"📤 <b>Yesterday ({day:%d %b})</b>"]
    for row in rows:
        where = esc(row["platform"])
        what = esc(row.get("pillar") or "")
        if row["status"] == "published":
            link = row.get("permalink") or ""
            # The link is the whole point of this section: a claim that
            # something was published, which you can check in one tap.
            suffix = f' — <a href="{esc(link)}">open</a>' if link else " (no permalink returned)"
            lines.append(f"  ✅ {where} · {what}{suffix}")
        else:
            lines.append(f"  ❌ {where} · {what} — {esc((row.get('error') or '')[:120])}")
    return "\n".join(lines)


# ── 2. today ─────────────────────────────────────────────────────────────────
def _plan(config, today: date) -> str:
    """Every slot due today, in time order."""
    start = config.start_date()
    boosting = boost_active(start, config.boost_weeks, today)
    enabled = config.active_platforms()

    slots = [
        s for s in WEEK
        if s.weekday == today.weekday() and s.platform in enabled
        and (boosting or not s.boost)
    ]
    if not slots:
        return "📅 <b>Today</b>\n  nothing scheduled — the gap is deliberate"

    lines = [f"📅 <b>Today — {len(slots)} post(s)</b>"]
    for slot in sorted(slots, key=lambda s: (s.hour, s.minute)):
        pillar = phase.substitute(slot.pillar, start, today)
        swapped = f" (was {esc(slot.pillar)})" if pillar != slot.pillar else ""
        region = (
            regions.for_slot(slot.platform, slot.hour, today).code
            if config.geo_targeting else "--"
        )
        boost = " 🚀" if slot.boost else ""
        lines.append(
            f"  {slot.hour:02d}:{slot.minute:02d} {esc(region)} · "
            f"<b>{esc(slot.platform)}</b> · {esc(pillar)}{swapped} · "
            f"{esc(slot.fmt)}{boost}"
        )
    lines.append("  <i>each ±25 min, so the exact minute varies</i>")
    return "\n".join(lines)


# ── 3. your hands ────────────────────────────────────────────────────────────
def _manual(config) -> str:
    """Drafts waiting to be posted by a person.

    Listed rather than re-sent: the full copyable text went out when the draft
    was written, and repeating three tweet threads every morning would bury the
    rest of the brief. This says what is outstanding and how to clear it.
    """
    from wizcore.db.conn import connect

    from platforms.manual import pending

    try:
        with connect(config.database_url) as conn:
            rows = pending(conn, limit=20)
    except Exception:
        log.warning("could not read the manual queue", exc_info=True)
        return ""

    if not rows:
        return "✍️ <b>Waiting on you</b>\n  nothing — the queue is clear"

    lines = [f"✍️ <b>Waiting on you — {len(rows)}</b>"]
    for row in rows:
        when = row["created_at"].strftime("%d %b") if row.get("created_at") else ""
        lines.append(
            f"  <code>/done {row['id']}</code> · {esc(row['platform'])} · "
            f"{esc(row.get('pillar') or '')} · {when}"
        )
    lines.append("  <i>the full text was sent when each was written — scroll back</i>")
    return "\n".join(lines)


def _trends(config) -> str:
    """One line on the trend funnel, only when something is ready."""
    if not config.trends_enabled:
        return ""
    try:
        from trends import angle as angle_mod

        ready = angle_mod.ready_count(config)
    except Exception:
        return ""
    if not ready:
        return "\n📰 no trend angle is ready — most days genuinely have none"
    return f"\n📰 <b>{ready} trend angle(s) ready</b> — a timely post may be inserted"


def send_daily(config, today: date | None = None) -> dict:
    """Send the brief only when something is actually waiting on a person.

    The brief used to arrive every morning regardless, on the reasoning that a
    per-post notification says nothing when nothing happens, so a quiet agent and
    a broken one look identical. That reasoning holds — but the answer to it is
    the portal, which shows the same three sections on demand and shows them for
    any day, not just this one.

    What a phone message is uniquely good at is the one section the portal cannot
    do anything about: drafts that only a human can post. So the brief now fires
    on that alone. A morning with an empty queue is silent, and silence has a
    single unambiguous meaning again — there is nothing for you to do.

    `compose()` is untouched and still builds the whole thing; `main.py --brief`
    prints it on demand, and the portal renders the same sections.
    """
    from wizcore.telegram.send import send

    # The "still broken" list is the other thing only a person can act on, and
    # the reason the brief may now fire with an empty queue: a dead lead source
    # or a crashing agent used to be announced once and then never again.
    health = _health_lines(config)

    expired = 0
    try:
        with connect_pending(config, expire=True) as rows:
            waiting = list(rows)
            expired = getattr(rows, "expired", 0)
    except Exception:
        log.warning("could not read the manual queue", exc_info=True)
        waiting = []

    if not waiting and not health:
        log.info("nothing broken and manual queue is clear; no brief sent")
        return {"brief_sent": 0, "brief_skipped": "nothing waiting", "drafts_expired": expired}

    lines: list[str] = []
    if health:
        lines += ["🚨 <b>Needs attention</b>", *(f"  {esc(x)}" for x in health), ""]
    if waiting:
        lines += [f"✍️ <b>{len(waiting)} draft(s) waiting on you</b>", ""]
        for row in waiting:
            when = row["created_at"].strftime("%d %b") if row.get("created_at") else ""
            lines.append(
                f"  <code>/done {row['id']}</code> · {esc(row['platform'])} · "
                f"{esc(row.get('pillar') or '')} · {when}"
            )
        lines.append("")
        lines.append("<i>Full text was sent when each was written. Drafts expire after "
                     "7 days.</i>")

    ok = send("\n".join(lines), topic="content", audience="content", dry_run=False)
    return {"brief_sent": int(bool(ok)), "brief_waiting": len(waiting),
            "brief_problems": len(health), "drafts_expired": expired}


class _Pending(list):
    """The pending rows, plus how many stale drafts were expired on the way."""

    expired: int = 0


@contextmanager
def connect_pending(config, expire: bool = False):
    """Pending manual drafts, as a context manager so the connection closes.

    With `expire`, drafts older than a week are retired first. They are copy
    about a moment that has passed, and without this the queue only ever grew:
    40 LinkedIn drafts were pending by 4 Oct and the brief listed them daily.
    """
    from wizcore.db.conn import connect

    from platforms.manual import expire_stale, pending

    with connect(config.database_url) as conn:
        expired = expire_stale(conn) if expire else 0
        rows = _Pending(pending(conn, limit=20))
        rows.expired = expired
        yield rows
