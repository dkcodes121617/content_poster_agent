"""Brand safety for timely content — a validator, never a prompt instruction.

The rule the owner set: **opinions about practices, never about people or
companies.** "Per-seat pricing for AI tools will age badly" is a take a buyer
can argue with. "Vendor X is bad" is a liability with no upside for a studio
whose prospects may be that vendor's customers.

This is code rather than a line in a prompt for the same reason
`no_write_endpoints.py` is code: a rule a model is asked to follow is a
suggestion, and the failure here is a published post that cannot be unpublished.

## Cool-off

Nothing under `TREND_COOL_OFF_HOURS` old. Breaking stories get corrected, and
confidently amplifying one that turns out wrong costs more than the reach gained
by being early. Six hours is enough for a bad story to be walked back and short
enough that the trend is still live.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

# Subject matter a software studio has no business commenting on. Matching is
# word-boundary, so "warfare" does not trip on "war" and "electionese" does not
# trip on "election".
NO_GO_TOPICS: tuple[str, ...] = (
    # politics and geopolitics
    "election", "elections", "president", "prime minister", "parliament",
    "congress", "senate", "political", "politics", "war", "invasion", "military",
    "sanctions", "protest", "riot", "coup", "immigration", "deportation",
    # identity and belief
    "religion", "religious", "abortion", "gender identity", "racism", "racist",
    "antisemitic", "islamophobi", "caste",
    # tragedy
    "shooting", "massacre", "terrorist", "terrorism", "earthquake", "hurricane",
    "wildfire", "famine", "pandemic outbreak", "died", "death toll", "suicide",
    "assassination", "hostage",
    # things that read as gloating or punching down
    "layoffs", "laid off", "fired staff", "bankruptcy", "shut down operations",
    "data breach", "hacked", "lawsuit", "sued", "fraud", "arrested", "indicted",
)

# A take on a named company crosses from "practice" to "person". Naming a
# company factually ("X shipped Y") is fine and necessary; naming one as the
# TARGET of a judgement is not, so this pairs a company mention with a verdict
# word rather than banning names outright.
_VERDICT = re.compile(
    r"\b(?:terrible|awful|garbage|scam|ripoff|rip-off|useless|incompetent|"
    r"dishonest|lying|lied|fraudulent|joke|disaster|embarrassing|pathetic|"
    r"greedy|predatory|shameless)\b",
    re.I,
)
# Only fires when a verdict word sits near a capitalised name.
_NAMED = re.compile(r"\b[A-Z][a-zA-Z0-9]{2,}(?:\s+[A-Z][a-zA-Z0-9]+)?\b")


def topic_blocked(text: str) -> str:
    """The no-go topic found in `text`, or '' if clean."""
    lowered = (text or "").lower()
    for topic in NO_GO_TOPICS:
        if re.search(rf"\b{re.escape(topic)}", lowered):
            return topic
    return ""


def targets_a_company(text: str) -> str:
    """A judgement aimed at a named entity, or '' if clean.

    Deliberately narrow. Criticising a *practice* is the entire point of the
    POV pillar, so this only fires when a verdict word appears within about a
    clause of a capitalised name.
    """
    for match in _VERDICT.finditer(text or ""):
        window = text[max(0, match.start() - 80) : match.end() + 80]
        for name in _NAMED.findall(window):
            if name.lower() in _ALLOWED_NAMES:
                continue
            return f"{name} + '{match.group(0)}'"
    return ""


# Capitalised words that are not companies being judged: sentence starters,
# our own brand, and generic tech nouns.
_ALLOWED_NAMES = frozenset(
    ["the", "this", "that", "these", "those", "it", "its", "and", "but", "for", "with", "from", "when", "what", "why", "how", "your", "you", "our", "we", "they", "there", "here", "most", "some", "every", "after", "before", "wizcodes", "ai", "api", "saas", "mvp", "seo", "ui", "ux", "most", "one", "two", "three", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
)


def too_fresh(published_at, cool_off_hours: int) -> bool:
    """True while a story is younger than the cool-off window."""
    if not published_at:
        # Unknown age is treated as fresh. An item with no timestamp is usually
        # a syndicated headline, and guessing "old enough" on a breaking story
        # is the mistake the cool-off exists to prevent.
        return True
    age = datetime.now(UTC) - published_at
    return age.total_seconds() < cool_off_hours * 3600


def check_item(title: str, summary: str, published_at, cool_off_hours: int) -> str:
    """One reason this item must not be used, or '' if it is safe."""
    blob = f"{title}\n{summary}"
    topic = topic_blocked(blob)
    if topic:
        return f"no-go topic: {topic!r}"
    if too_fresh(published_at, cool_off_hours):
        return f"under the {cool_off_hours}h cool-off"
    return ""


def check_draft(text: str) -> list[str]:
    """Reasons a finished draft must not publish. Runs after generation."""
    reasons: list[str] = []
    topic = topic_blocked(text)
    if topic:
        reasons.append(f"[safety] no-go topic: {topic!r}")
    targeted = targets_a_company(text)
    if targeted:
        reasons.append(
            f"[safety] judgement aimed at a named entity ({targeted}) - "
            "criticise the practice, not the company"
        )
    return reasons
