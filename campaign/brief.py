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
    """Compose and send. Returns counters for the run log."""
    from wizcore.telegram.send import send

    try:
        text = compose(config, today)
    except Exception:
        log.exception("could not compose the daily brief")
        return {"brief_sent": 0}
    # Not silent: this is the one message of the day that should make a sound.
    ok = send(text, topic="content", dry_run=False)
    return {"brief_sent": int(bool(ok))}
