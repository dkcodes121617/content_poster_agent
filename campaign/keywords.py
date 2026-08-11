"""The search phrases a post is written to be found for.

## What this is for

LinkedIn builds a post's public URL from its **opening words**:

    linkedin.com/posts/wizcodes_free-prototype-before-hiring-a-developer-activity-7…
                                └── generated from roughly the first ten words ──┘

dev.to does the same from an article's title, and that one is live today. So the
first line of a post is not only the hook — it is the URL, and the URL is a
ranking signal on a domain with far more authority than ours will have for
years.

The job here is to supply a phrase the opening line should contain **naturally**.
Not to stuff it. A keyword-first opener is exactly the machine-written tell
`validators/voice.py` exists to catch, and "we are the best software company" is
an unverifiable superlative the grounding gate would reject on sight. The rule is
that the phrase appears in a sentence a person would actually write.

## Where these came from

`details.md` §18 — the site's own keyword strategy — is the source, so a post and
the page it drives traffic to are fighting for the same phrases rather than
competing. Nothing here was invented to sound good.

Two things were added from research (8 Aug 2026) rather than from the site:

  * **"founder-run studio"** is emerging as its own category — "agency-grade work
    at freelancer-grade pricing because the founders do the work themselves" —
    and it describes WizCodes exactly while being far less contested than
    "software development agency".
  * **Comparison queries** ("freelancer vs agency vs studio") are heavily served
    by competitors' blogs, which is itself the signal: agencies only write those
    posts because the traffic converts.

## On volume

The tiers below rank by **intent**, which is decidable from the phrasing: someone
typing "freelancer vs agency vs studio" is choosing a supplier this month.
Nothing here claims a monthly search volume, because verifying that needs a
keyword tool we do not have — treat `weight` as commercial intent, not traffic.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import date

from campaign.calendar import today_ist

# Intent tiers, highest first. The tier is the whole point: a "decision" phrase is
# worth ten "learn" phrases because the person typing it has a budget and a
# shortlist.
TIERS = ("decision", "cost", "problem", "learn")
TIER_WEIGHT = {"decision": 4, "cost": 3, "problem": 2, "learn": 1}


@dataclass(frozen=True)
class Phrase:
    text: str
    tier: str
    # Pillars this phrase can be written into honestly. A cost phrase on a
    # `proof` post works ("what this actually cost to build" — as a story, not a
    # number); on `client_voice` it does not.
    pillars: tuple[str, ...]
    # "" means every region. Regional phrases carry local vocabulary, which is
    # what makes them findable — a UK buyer does not search "vendor".
    region: str = ""
    service: str = ""       # web | mobile | ai | ""


# ── decision: choosing a supplier, now ───────────────────────────────────────
_DECISION = [
    ("freelancer vs agency vs studio", ("pov", "teach"), "", ""),
    ("alternative to expensive software agencies", ("pov", "teach"), "", ""),
    ("offshore development without agency overhead", ("pov", "teach"), "", ""),
    ("free prototype before hiring a developer", ("process", "direct_offer"), "", ""),
    ("founder-run software studio", ("pov", "process"), "", ""),
    ("how to choose a software development partner", ("teach", "pov"), "", ""),
    ("questions to ask a software agency before signing", ("teach",), "", ""),
    ("own your source code software agency", ("pov", "teach"), "", ""),
    ("fixed scope vs hourly billing software", ("teach", "pov"), "", ""),
    ("MVP development agency for non-technical founders", ("teach", "proof"), "", ""),
    ("app development agency near me", ("teach", "proof"), "GB", ""),
    ("software development company for US startups", ("proof", "teach"), "US", ""),
    ("GDPR compliant software development partner", ("teach", "proof"), "EU", ""),
]

# ── cost: budgeting, still shortlisting ──────────────────────────────────────
_COST = [
    ("how much does a SaaS MVP cost", ("teach",), "", ""),
    ("cost to build an app for a small business", ("teach",), "US", ""),
    ("website redesign cost for a small business", ("teach",), "GB", ""),
    ("what software development actually costs", ("teach", "pov"), "", ""),
    ("why software quotes vary so much", ("teach", "pov"), "", ""),
    ("hidden costs of hiring a development agency", ("teach", "pov"), "", ""),
    ("affordable software development for startups", ("teach", "proof"), "", ""),
    ("MVP development cost for a non-technical founder", ("teach",), "", ""),
]

# ── problem: has the pain, has not named the solution ────────────────────────
# These carry `client_voice` too. A testimonial is a client describing the
# problem they had, so the phrase somebody searches for that problem is the
# phrase that post is already about — no stretching required.
_PROBLEM = [
    ("my website is slow on mobile", ("proof", "teach", "client_voice"), "", "web"),
    ("customers call instead of booking online", ("proof", "teach", "client_voice"), "", "web"),
    ("my developer disappeared mid project", ("pov", "teach", "client_voice"), "", ""),
    ("software project ran over budget", ("pov", "teach"), "", ""),
    ("manual data entry is eating my team's time", ("proof", "teach", "client_voice"), "", "ai"),
    ("support tickets piling up small business", ("proof", "teach", "client_voice"), "", "ai"),
    ("spreadsheet is running my business", ("teach", "proof"), "", "web"),
    ("can't hire developers fast enough", ("pov", "teach"), "", ""),
]

# ── learn: educating, months from buying ─────────────────────────────────────
_LEARN = [
    ("build an AI agent for my business", ("teach", "timely"), "", "ai"),
    ("LLM integration for a SaaS product", ("teach", "timely"), "", "ai"),
    ("Next.js development for startups", ("teach", "proof"), "", "web"),
    ("React Native vs Flutter for a first app", ("teach", "pov"), "", "mobile"),
    ("how to brief a software developer", ("teach", "process"), "", ""),
    ("what goes in a good software brief", ("teach", "process"), "", ""),
    ("workflow automation for small business", ("teach", "timely"), "", "ai"),
    ("AI tools for small business owners", ("teach", "timely"), "", "ai"),
]

PHRASES: tuple[Phrase, ...] = tuple(
    Phrase(text, tier, pillars, region, service)
    for tier, rows in (
        ("decision", _DECISION), ("cost", _COST),
        ("problem", _PROBLEM), ("learn", _LEARN),
    )
    for text, pillars, region, service in rows
)

# Platforms whose public URL is built from the post's own opening words, so the
# first line is worth optimising. Everywhere else the phrase is still useful for
# on-platform search, but it is not a URL.
SLUG_PLATFORMS = frozenset({"linkedin", "devto"})


def eligible(pillar: str, region: str = "", service: str = "") -> list[Phrase]:
    """Phrases that can be written into this post honestly."""
    return [
        p for p in PHRASES
        if pillar in p.pillars
        and (not p.region or not region or p.region == region)
        and (not p.service or not service or p.service == service)
    ]


def pick(
    pillar: str,
    *,
    platform: str = "",
    region: str = "",
    service: str = "",
    used: list[str] | None = None,
    today: date | None = None,
) -> Phrase | None:
    """One phrase for this post, or None when nothing fits.

    Weighted toward high intent, not uniform: a "decision" phrase is four times
    as likely as a "learn" one, because the person typing it is choosing a
    supplier this month rather than reading around a subject.

    Seeded by day and slot, so a retry writes the same post rather than a
    different one — the same rule the recipe picker follows, for the same reason.
    """
    pool = eligible(pillar, region, service)
    recent = set(used or [])
    fresh = [p for p in pool if p.text not in recent]
    pool = fresh or pool
    if not pool:
        return None
    rng = random.Random(f"{(today or today_ist()).isoformat()}:{platform}:{pillar}:{region}")
    return rng.choices(pool, weights=[TIER_WEIGHT[p.tier] for p in pool])[0]


def brief(phrase: Phrase, platform: str) -> str:
    """The instruction that goes into the prompt. Never 'use this keyword'."""
    slug_note = (
        f"\n  On {platform}, the post's public URL is built from these opening words, "
        "so they are also the page's address in search results."
        if platform in SLUG_PLATFORMS else ""
    )
    return (
        "SEARCH PHRASE FOR THE OPENING LINE\n"
        f'  "{phrase.text}"\n\n'
        "  Your FIRST sentence should contain this phrase, or a close natural "
        "variation of it, because that is what somebody types when they are "
        "looking for what we do.{slug}\n\n"
        "  It has to read like a sentence a person wrote. "
        '"Most founders start by comparing a freelancer vs an agency vs a studio" '
        "is right. Naming it as a heading, repeating it, or opening with a claim "
        'like "we are the best" is wrong - a superlative we cannot prove is '
        "rejected automatically, and a keyword-shaped opener reads as spam to the "
        "reader before it ever reaches search."
    ).format(slug=slug_note)


# Close enough to count. LinkedIn slugs are lowercased and hyphenated, so
# punctuation and case never matter; word order and stemming do.
_STOP = {"a", "an", "the", "for", "to", "of", "my", "your", "is", "are", "in", "on", "and"}


def _key_words(phrase: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", phrase.lower())
    return [w for w in words if w not in _STOP and len(w) > 2]


def in_opening(text: str, phrase: str, words: int = 14) -> bool:
    """Whether the phrase's substance is in the opening words of `text`.

    Matched on content words rather than the literal string, because the natural
    sentence is almost never the phrase verbatim — "comparing a freelancer vs an
    agency vs a studio" has to count for "freelancer vs agency vs studio", or the
    check would force exactly the robotic phrasing it exists to prevent.

    Two thirds is the bar: enough that the slug carries the query, loose enough
    that a writer can put a word in between.
    """
    opening = " ".join(re.split(r"\s+", (text or "").strip())[:words]).lower()
    wanted = _key_words(phrase)
    if not wanted:
        return False
    hits = sum(1 for w in wanted if re.search(rf"\b{re.escape(w)}\w*", opening))
    return hits >= max(2, round(len(wanted) * 0.66))


def slug_preview(text: str, words: int = 10) -> str:
    """What LinkedIn would put in the URL, as far as we can tell.

    Their algorithm is undocumented and has changed before, so this is a
    prediction, not a promise. `platforms/linkedin.py` records the permalink the
    API actually returns, which is how this gets corrected from evidence rather
    than from assumption.
    """
    parts = re.findall(r"[a-z0-9]+", (text or "").lower())
    return "-".join(parts[:words])
