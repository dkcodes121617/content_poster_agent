"""Campaign phasing — the launch plan, revised 9 Aug 2026.

## What changed, and why the earlier version was wrong for this studio

The first design was **awareness-first**: two weeks of proof and process with
opinions, offers and news all withheld, on the argument that a visitor landing
on a two-week-old profile should find evidence rather than opinions.

That argument is sound for an account starting from nothing. It is wrong here,
for a reason that was in front of me the whole time: **the credibility already
exists, it just lives on the website.** 26 delivered projects, 13 public
testimonials, clients in 11 countries. A feed withholding opinion for a fortnight
is not building trust it lacks — it is declining to use trust it already has.

Two consequences follow, and the second is the bigger one:

**Timely content should run from day one.** It was deferred longest and it is the
single best discovery mechanism a new account has, because a timely post rides a
conversation that is already happening instead of trying to start one. Waiting
six weeks to use the trend layer meant waiting six weeks for the only content
type that reaches people who have never heard of us.

**Search-intent content should lead.** Teaching posts answering "what does a SaaS
MVP cost" or "freelancer vs agency vs studio" are found by people who are
actively choosing a supplier. That is not awareness. That is the bottom of the
funnel, and it is where a studio with no ad budget wins.

## What is still withheld, and why only this

`direct_offer` — one selling post in thirty even at full strength — stays out of
the first fortnight. Not out of caution about credibility, but because a feed
needs something in it before a sales post has any context to sit in. It arrives
in week three at 2%.

Nothing else is held back. The phases below shift *emphasis*; they no longer
forbid.

## Where the mix is heading

    launch      weeks 1-2   prove it, answer what buyers search, react to news
    compound    weeks 3-6   same, plus the offer, weighted further toward timely
    full        week 7+     steady state

The trajectory is deliberate: proof and teach start heaviest because they carry
search intent, and timely grows because by then the archive gives a reaction
something to stand on.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from campaign.calendar import today_ist

log = logging.getLogger("content_poster.phase")


@dataclass(frozen=True)
class Phase:
    name: str
    weeks: str
    mix: dict[str, float]
    withheld: tuple[str, ...]
    note: str

    def allows(self, pillar: str) -> bool:
        return pillar not in self.withheld and self.mix.get(pillar, 0) > 0


LAUNCH = Phase(
    "launch", "1-2",
    {"proof": 0.28, "teach": 0.26, "timely": 0.16, "pov": 0.16,
     "process": 0.12, "client_voice": 0.02},
    withheld=("direct_offer",),
    note="Lead with proof and the questions buyers actually search. React to news "
         "from day one - it is the only content that reaches strangers.",
)
COMPOUND = Phase(
    "compound", "3-6",
    {"proof": 0.24, "teach": 0.24, "timely": 0.18, "pov": 0.18,
     "process": 0.10, "client_voice": 0.04, "direct_offer": 0.02},
    withheld=(),
    note="The offer joins the mix. Timely grows: the archive now gives a "
         "reaction something to stand on.",
)
FULL = Phase(
    "full", "7+",
    {"proof": 0.22, "teach": 0.22, "timely": 0.20, "pov": 0.18,
     "process": 0.10, "client_voice": 0.05, "direct_offer": 0.03},
    withheld=(),
    note="Steady state. One selling post in about thirty.",
)

PHASES = (LAUNCH, COMPOUND, FULL)
# (phase, first week it applies). Weeks are 1-indexed from the start date.
_SCHEDULE = ((LAUNCH, 1), (COMPOUND, 3), (FULL, 7))


def current(start: date | None, today: date | None = None) -> Phase:
    """The phase in force. `FULL` when no start date is configured.

    Defaulting to FULL rather than LAUNCH is deliberate: an unset start date on
    a system that has been running for months would otherwise re-withhold the
    offer, and "the agent quietly stopped making its offer" is much harder to
    notice than a missing config value.
    """
    if not start:
        return FULL
    today = today or today_ist()
    if today < start:
        return LAUNCH
    week = ((today - start).days // 7) + 1
    phase = FULL
    for candidate, from_week in _SCHEDULE:
        if week >= from_week:
            phase = candidate
    return phase


def week_of(start: date | None, today: date | None = None) -> int:
    if not start:
        return 0
    today = today or today_ist()
    return max(((today - start).days // 7) + 1, 1)


def mix(start: date | None, today: date | None = None) -> dict[str, float]:
    return dict(current(start, today).mix)


def allows(pillar: str, start: date | None, today: date | None = None) -> bool:
    return current(start, today).allows(pillar)


def substitute(pillar: str, start: date | None, today: date | None = None) -> str:
    """A pillar this phase permits, when the calendar asks for one it does not.

    Returns a *replacement* rather than skipping the slot. Skipping would mean
    the first fortnight publishing less often than the calendar says, and
    consistency is the entire point of having a calendar.

    With only `direct_offer` withheld and only for two weeks, this now fires
    roughly twice in the whole launch. That is the intended change: the previous
    design substituted a third of every week's posts.
    """
    phase = current(start, today)
    if phase.allows(pillar):
        return pillar
    ranked = sorted(phase.mix.items(), key=lambda kv: (-kv[1], kv[0]))
    replacement = ranked[0][0] if ranked else "proof"
    log.info("phase %s withholds %s; substituting %s", phase.name, pillar, replacement)
    return replacement


def describe(start: date | None, today: date | None = None) -> str:
    """One line for `--schedule` and the digest."""
    phase = current(start, today)
    if not start:
        return f"phase: {phase.name} (no CAMPAIGN_START_DATE set - steady state)"
    week = week_of(start, today)
    held = f" | withheld: {', '.join(phase.withheld)}" if phase.withheld else " | nothing withheld"
    return f"phase: {phase.name} (week {week}, weeks {phase.weeks}){held}"
