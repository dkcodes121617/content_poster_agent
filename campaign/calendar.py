"""The weekly rhythm and the pillar mix — CAMPAIGN.md §4 and §6 as code.

Fixed slots, because an audience learns a schedule and a schedule makes this
agent's job deterministic: "what should I post right now?" has one answer, not a
judgement call.

Two details that look cosmetic and are not:

**Saturday is light and Sunday is empty.** Accounts that post seven days a week
at identical times read as automated, because they are. The gap is a signal.

**Every slot is jittered by ±25 minutes.** A post that lands at exactly 20:00:00
every single time is a fingerprint.

The 3% direct-offer share is also not a typo. One selling post in roughly thirty;
everything else earns the right to make it. An account that sells in every post
gets muted.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Pillar -> share of all posts. CAMPAIGN.md §4.
# TRENDS.md §6 rebalanced this to make room for timely content without
# displacing proof, which is what actually converts.
PILLAR_MIX: dict[str, float] = {
    "proof": 0.25,
    "teach": 0.20,
    "timely": 0.20,
    "pov": 0.15,
    "process": 0.12,
    "client_voice": 0.05,
    "direct_offer": 0.03,
}


@dataclass(frozen=True)
class Slot:
    weekday: int          # 0 = Monday
    hour: int             # IST
    minute: int
    platform: str
    pillar: str
    fmt: str              # carousel | single | text | article | pin
    slides: int = 0

    @property
    def key(self) -> str:
        return f"{self.weekday}:{self.hour:02d}:{self.platform}:{self.pillar}"


# CAMPAIGN.md §6, all times IST. Weekly totals: Instagram 3, Facebook 3,
# Threads 5, Pinterest 2. LinkedIn's three slots are defined but only fire once
# PLATFORMS_ENABLED includes it, so switching the platform on needs no code
# change — which is the whole point of writing them down now.
WEEK: list[Slot] = [
    # Monday
    Slot(0, 11, 0, "instagram", "proof", "carousel", 6),
    Slot(0, 21, 0, "threads", "pov", "text"),
    Slot(0, 15, 0, "pinterest", "proof", "pin"),
    # Tuesday
    Slot(1, 18, 30, "linkedin", "teach", "text"),
    Slot(1, 19, 0, "x", "teach", "thread"),
    Slot(1, 20, 0, "facebook", "process", "single"),
    Slot(1, 21, 0, "threads", "proof", "text"),
    # Wednesday
    Slot(2, 18, 30, "linkedin", "proof", "carousel", 8),
    Slot(2, 11, 0, "instagram", "process", "carousel", 6),
    Slot(2, 21, 0, "threads", "process", "text"),
    # Thursday
    Slot(3, 18, 30, "linkedin", "pov", "text"),
    Slot(3, 19, 0, "x", "proof", "thread"),
    Slot(3, 20, 0, "facebook", "client_voice", "single"),
    Slot(3, 21, 0, "threads", "pov", "text"),
    Slot(3, 15, 0, "pinterest", "teach", "pin"),
    # Friday
    Slot(4, 11, 0, "instagram", "teach", "carousel", 5),
    Slot(4, 19, 0, "x", "pov", "thread"),
    Slot(4, 20, 0, "facebook", "proof", "single"),
    Slot(4, 21, 0, "threads", "teach", "text"),
    # Saturday - deliberately one light, human line and nothing else.
    Slot(5, 21, 0, "threads", "process", "text"),
    # Sunday - empty on purpose.
]


def ist_now(tz: str = "Asia/Kolkata") -> datetime:
    return datetime.now(ZoneInfo(tz))


def due_slots(
    now: datetime,
    enabled: list[str],
    window_minutes: int = 45,
    jitter_minutes: int = 25,
) -> list[Slot]:
    """Slots whose jittered time falls inside the window ending at `now`.

    The jitter is **deterministic per slot per day**, seeded from the date and
    the slot key. That matters: the scheduler runs repeatedly, and a random
    offset recomputed on each run would make a slot drift in and out of the
    window, so it would either publish twice or never. Seeding makes the offset
    stable for a given day while still varying across days.

    Idempotency does not rest on this — `core.external_actions` is what actually
    prevents a double post — but a scheduler that is merely *probably* right is
    not worth the debugging.
    """
    out: list[Slot] = []
    for slot in WEEK:
        if slot.platform not in enabled:
            continue
        if slot.weekday != now.weekday():
            continue
        rng = random.Random(f"{now.date().isoformat()}:{slot.key}")
        offset = rng.randint(-jitter_minutes, jitter_minutes)
        scheduled = now.replace(
            hour=slot.hour, minute=slot.minute, second=0, microsecond=0
        ) + timedelta(minutes=offset)
        if scheduled <= now < scheduled + timedelta(minutes=window_minutes):
            out.append(slot)
    return out


def timely_slot(platform: str, now: datetime) -> Slot:
    """An off-calendar slot for a trend worth posting today.

    TRENDS.md §6: timely posts are the only ones that may be inserted outside
    the fixed rhythm, because a take posted three days late is worthless — that
    is the entire advantage of having a trend layer. The one-per-platform-per-day
    cap lives in `content.trend_inserts`, not here, since the cap is per day and
    this function has no idea what earlier runs did.
    """
    fmt = {"x": "thread", "instagram": "carousel"}.get(platform, "text")
    return Slot(
        weekday=now.weekday(),
        hour=now.hour,
        minute=now.minute,
        platform=platform,
        pillar="timely",
        fmt=fmt,
        slides=5 if fmt == "carousel" else 0,
    )


# Platforms where a same-day reaction actually lands. Deliberately excludes
# Pinterest (evergreen visual search, nobody browses it for news) and dev.to
# (event-driven syndication, not reactions).
TIMELY_PLATFORMS = ("threads", "linkedin", "x", "facebook")


def slot_idempotency_parts(slot: Slot, now: datetime) -> tuple[str, ...]:
    """What makes this slot unique for one day.

    Date plus slot, deliberately NOT the generated copy: if a run publishes and
    then a retry regenerates slightly different wording, a content-derived key
    would look like a brand-new action and post twice. The slot is the thing
    that must happen once.
    """
    return (now.date().isoformat(), slot.platform, slot.pillar, str(slot.weekday), str(slot.hour))
