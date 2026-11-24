"""First-person studio stories must be about a real, named project.

Seen in the 24 Nov writer benchmark, after both the brief and the editor said
not to: "We added a Priority field to every lead. Sales ignored it..." and "A
client asked us to add an 'Industry' field to their CRM...". Vivid, and it
scored 8/10 with the editor, but it is a WizCodes story that never happened.
The grounding gate checks figures and names; an anecdote with neither sails
through it.

The rule is deliberately narrow: a sentence that tells something as OUR
experience ("we added", "a client asked us", "one of our clients") is allowed
only when the same post names a project or client from the site facts. General
lessons are still welcome - written as a scenario about someone else ("A team
adds a Priority field..."), which is honest and reads just as well.
"""
from __future__ import annotations

import re

# Studio-experience openers. Each needs a named project in the post to stand.
_PATTERNS = [
    # "a client asked / added / wanted ..." - past-tense narrative about a client.
    r"\ba\s+client\s+(?:once\s+|recently\s+)?(?:\w+ed|had|told|came|sent|wrote|built|kept|took|made|said)\b",
    # "one client added X. Another added Y." - seen in the 24 Nov bench.
    r"\b(?:one|another)\s+client\b",
    r"\bone\s+of\s+our\s+clients\b",
    r"\bour\s+client\s+(?:asked|wanted|told|needed|had)\b",
    r"\bwe\s+(?:once\s+|recently\s+)?(?:added|tried|learned|learnt|discovered|watched|saw)\b",
    r"\b(?:last|this)\s+(?:week|month|year)\s*,?\s+we\b",
]
_RX = re.compile("|".join(_PATTERNS), re.IGNORECASE)


def _named_anchors(snapshot) -> list[str]:
    names: list[str] = []
    for p in getattr(snapshot, "projects", None) or []:
        for value in (getattr(p, "name", ""), getattr(p, "client", "")):
            value = (value or "").strip()
            if len(value) >= 3:
                names.append(value.lower())
    return names


def check(text: str, snapshot) -> list[str]:
    """Reasons to reject, or [] when every studio story is anchored."""
    hit = _RX.search(text or "")
    if not hit:
        return []
    lowered = (text or "").lower()
    if any(name in lowered for name in _named_anchors(snapshot)):
        return []
    return [(
        f"tells a studio story ({hit.group(0)!r}) without naming a real project from "
        "the facts - it reads as invented. Either tell it about a named project, or "
        "rewrite it as a scenario about someone else ('A team adds...')."
    )]
