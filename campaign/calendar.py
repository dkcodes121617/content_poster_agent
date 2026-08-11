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
from datetime import date, datetime, timedelta
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
    # Fires only during the launch boost (BOOST_WEEKS from CAMPAIGN_START_DATE).
    # A profile with three posts on it converts worse than one with thirty, and
    # the first weeks are exactly when a lead is most likely to go and look.
    boost: bool = False

    @property
    def key(self) -> str:
        return f"{self.weekday}:{self.hour:02d}:{self.platform}:{self.pillar}"


# CAMPAIGN.md §6, all times IST. Weekly totals: Instagram 3, Facebook 3,
# Threads 5, Pinterest 2. LinkedIn's three slots are defined but only fire once
# PLATFORMS_ENABLED includes it, so switching the platform on needs no code
# change — which is the whole point of writing them down now.
# The hours are now REGIONAL, and that changed several of them.
#
# CONTENT_SYSTEM.md §4 added per-region posting windows, and printing the
# calendar against them exposed that almost every slot resolved to the US. The
# reason was worse than a rotation bug: the three Instagram slots sat at 11:00
# IST, which is **01:30 Eastern and 05:30 in the UK**. That hour served nobody.
# It had never been noticed because nothing in the system had an opinion about
# where a reader was.
#
#   12:30-15:00 IST  ->  EU morning  (09:00 CET)
#   13:30-16:00 IST  ->  UK morning  (09:00 BST)
#   18:30-21:00 IST  ->  US morning  (09:00 ET)
#
# Volume is unchanged — the same 20 slots, moved. Adding slots to reach three
# markets would contradict §5's whole argument about cadence over burst.
# ── Weighted for a launch with no followers ──
#
# The question a launch calendar has to answer is: which channels work when
# nobody is subscribed yet? Only two kinds do.
#
#   **Search channels.** Pinterest is a search engine, not a feed — a pin ranks
#   in Pinterest search and Google Images and keeps working for months, with no
#   audience required. dev.to publishes on a real indexable slug. These compound.
#   Pinterest therefore goes from 2/week to 4, which is the single biggest change
#   here and the cheapest reach in the whole plan.
#
#   **Conversation channels.** Threads currently has the best organic reach of
#   anything in the Meta family for text, and its algorithm surfaces replies to
#   people who do not follow you. 5/week to 6.
#
# Facebook stays at 3 and expectations there should be low: organic page reach
# for a new page is close to nothing, and it is in the plan as presence and as
# the place a Google search for the brand name lands, not as a growth channel.
#
# The three LinkedIn slots stay defined and simply do not fire until
# PLATFORMS_ENABLED includes it — which is the whole point of writing them down
# now. When it lands the week goes from 22 slots to 25 with no code change.
WEEK: list[Slot] = [
    # Monday
    Slot(0, 13, 30, "instagram", "proof", "carousel", 6),      # UK
    Slot(0, 15, 0, "pinterest", "proof", "pin"),               # UK/EU
    Slot(0, 21, 0, "threads", "pov", "text"),                  # US
    # Tuesday
    Slot(1, 12, 30, "pinterest", "teach", "pin"),              # EU
    Slot(1, 14, 0, "threads", "proof", "text"),                # UK
    Slot(1, 18, 30, "linkedin", "teach", "text"),              # US
    Slot(1, 19, 0, "x", "teach", "thread"),                    # US
    Slot(1, 20, 0, "facebook", "process", "single"),           # US
    # Wednesday
    Slot(2, 12, 30, "instagram", "process", "carousel", 6),    # EU
    Slot(2, 16, 0, "threads", "teach", "text"),                # UK
    Slot(2, 18, 30, "linkedin", "proof", "carousel", 8),       # US
    Slot(2, 21, 0, "threads", "process", "text"),              # US
    # Thursday
    Slot(3, 15, 0, "pinterest", "teach", "pin"),               # UK/EU
    Slot(3, 18, 30, "linkedin", "pov", "text"),                # US
    Slot(3, 19, 0, "x", "proof", "thread"),                    # US
    Slot(3, 20, 0, "facebook", "client_voice", "single"),      # US
    Slot(3, 21, 0, "threads", "pov", "text"),                  # US
    # Friday
    Slot(4, 13, 0, "instagram", "teach", "carousel", 5),       # UK/EU
    Slot(4, 15, 0, "pinterest", "proof", "pin"),               # UK/EU
    Slot(4, 19, 0, "x", "pov", "thread"),                      # US
    Slot(4, 20, 0, "facebook", "proof", "single"),             # US
    Slot(4, 21, 0, "threads", "teach", "text"),                # US
    # Saturday - deliberately one light, human line and nothing else.
    Slot(5, 16, 0, "threads", "process", "text"),              # UK
    # Sunday - empty on purpose. An account that posts seven days a week at
    # identical times reads as automated, because it is.

    # ══ Launch boost — the first BOOST_WEEKS only ══════════════════════════
    #
    # Starting from zero, an empty profile is a conversion problem: a lead who
    # clicks through from an email or a search result and finds four posts is a
    # lead you have just lost. Archive depth is worth building fast.
    #
    # But NOT uniformly, and the asymmetry is the whole design:
    #
    #   **Pinterest triples.** It is a search index, not a feed. Several pins
    #   for the same subject aimed at different phrases is standard practice
    #   there, not spam, and nobody's home page fills up with them. This is
    #   free archive depth and it is the bulk of the boost.
    #
    #   **Threads goes up by half.** It tolerates volume better than anything
    #   else in the Meta family and its reach is conversation-driven.
    #
    #   **Instagram and Facebook barely move.** A brand-new account posting at
    #   triple rate with no engagement history is the exact shape Meta's spam
    #   heuristics look for, and early reach suppression does not wear off when
    #   you slow down. Two extra Instagram posts a week is worth having; six
    #   would risk the account itself.
    #
    #   **X does not move.** It is hand-published, so extra slots would only
    #   fill a human's queue.
    #
    # 20 slots a week becomes 35 - roughly 100 posts banked in three weeks.
    Slot(0, 11, 0, "pinterest", "teach", "pin", boost=True),
    Slot(0, 17, 0, "pinterest", "process", "pin", boost=True),
    Slot(0, 19, 30, "threads", "teach", "text", boost=True),
    Slot(1, 11, 0, "pinterest", "proof", "pin", boost=True),
    Slot(1, 16, 30, "instagram", "teach", "carousel", 5, boost=True),
    Slot(1, 17, 0, "pinterest", "pov", "pin", boost=True),
    Slot(2, 11, 0, "pinterest", "teach", "pin", boost=True),
    Slot(2, 14, 30, "threads", "pov", "text", boost=True),
    Slot(2, 17, 0, "pinterest", "process", "pin", boost=True),
    Slot(2, 20, 0, "facebook", "teach", "single", boost=True),
    Slot(3, 11, 0, "pinterest", "proof", "pin", boost=True),
    Slot(3, 13, 0, "threads", "process", "text", boost=True),
    Slot(3, 17, 0, "pinterest", "teach", "pin", boost=True),
    Slot(4, 11, 0, "pinterest", "pov", "pin", boost=True),
    Slot(4, 16, 30, "instagram", "proof", "carousel", 6, boost=True),
    Slot(4, 17, 0, "pinterest", "teach", "pin", boost=True),
    Slot(5, 12, 0, "pinterest", "proof", "pin", boost=True),
    Slot(5, 19, 0, "threads", "teach", "text", boost=True),
    # Sunday stays empty even during the boost. The gap is the signal.
]


def ist_now(tz: str = "Asia/Kolkata") -> datetime:
    return datetime.now(ZoneInfo(tz))


def today_ist(tz: str = "Asia/Kolkata") -> date:
    """Today, in the campaign's timezone — never `date.today()`.

    Modal containers run in UTC. Between 18:30 and 05:30 IST the two disagree
    about what day it is, which is most of the posting schedule. Everything
    seeded by date — the rotation ledger, the region rotation, the calendar
    jitter, the phase week — has to agree on which day it is or a single run
    plans a deck for Tuesday and records it as Monday.
    """
    return ist_now(tz).date()


def boost_active(start: date | None, weeks: int, today: date | None = None) -> bool:
    """Whether the launch boost is still running.

    Time-bounded rather than a switch, so it ends on its own. A boost somebody
    has to remember to turn off is a boost that runs for a year, and sustained
    triple volume is how an account stops looking like a studio and starts
    looking like a content farm.
    """
    if not start or weeks <= 0:
        return False
    today = today or today_ist()
    return today < start + timedelta(weeks=weeks)


def due_slots(
    now: datetime,
    enabled: list[str],
    window_minutes: int = 45,
    jitter_minutes: int = 25,
    boost: bool = False,
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
        if slot.boost and not boost:
            continue
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
