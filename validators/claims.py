"""The claims gate — no delivery timelines, no fixed prices for us.

CONTENT_SYSTEM.md §7, and the owner's instruction it came from:

  > please do not offer any timeline commitments for prototype or project
  > delivery under any circumstances, and do not mention our costs or pricing as
  > fixed numbers. You can compare our approach with others and discuss how
  > competitors typically price or deliver, but do not provide a specific cost
  > for us because it always depends on the requirements.

## Why this cannot live in the prompt

It is already in the prompt. It has to be a gate because this is precisely the
kind of thing a model does *helpfully* and unprompted: asked to write about a
free prototype, a good writer reaches for "and you'll have it in 48 hours"
because that is what makes the offer feel real. Nothing about the draft looks
wrong. It reads well, it is on-brand, and it commits the studio to something
nobody agreed to, on a public account that cannot un-post.

## The distinction the gate has to draw

The useful half of this subject is talking about how the industry prices and
delivers. Banning the topic would cost more than it saves, so the gate splits by
**who the claim is about**, the same way the grounding gate splits by what a
claim is about:

    "most agencies bill discovery as a paid phase"     -> allowed
    "typical agency retainers run into five figures"   -> allowed
    "our sites start at $5,000"                        -> rejected
    "a site like this costs about £8,000"              -> rejected (unattributed
                                                          on our own account
                                                          reads as our price)

Two further rules that took a false positive each to get right:

**Performance is not delivery.** "answers in under 200ms" is the single most
valuable sentence a proof post can contain. Sub-minute units are never a
delivery claim, so they are never checked.

**Money is not a price.** "developers earning under $1,000,000 a year" is a fact
about someone else's business. A currency amount is only a *price* when it sits
in a sentence that is pricing something — cost, quote, retainer, starting at.

## What "free prototype" does here

Nothing, and deliberately. The rule is about **numbers and durations**, not
about mentioning the offer. "A working prototype before any money changes hands"
is the core proposition, it is true, and it contains no figure — so it passes,
which it must, or the gate would ban the thing it exists to protect.
"""
from __future__ import annotations

import re

# ── who a sentence is about ──────────────────────────────────────────────────
_OURS = re.compile(
    r"\b(?:we|we'?re|we'?ll|we'?ve|us|our|ours|wizcodes|your\s+prototype|"
    # "you'll pay" and "you pay" are about paying *us*. Without them, the one
    # phrasing a writer reaches for when quoting a price reads as unattributed.
    r"you'?ll\s+(?:get|have|receive|pay|spend)|you\s+(?:pay|spend))\b",
    re.I,
)
_THEIRS = re.compile(
    r"\b(?:most|typical|typically|usually|often|generally|commonly|average|"
    r"industry|industries|market|competitors?|elsewhere|others?|"
    r"agenc(?:y|ies)|freelancers?|contractors?|vendors?|firms?|"
    r"studios(?!\s+like\s+ours)|the\s+going\s+rate|tend\s+to|many\s+\w+s)\b",
    re.I,
)

# ── durations ────────────────────────────────────────────────────────────────
# Sub-minute units are absent on purpose: "under 200ms" is a performance figure
# and is the best sentence in any proof post.
_DELIVERY_UNITS = r"(?:minute|hour|hr|day|week|month|quarter|year)s?"
_COUNT = r"(?:a|an|one|two|three|four|five|six|seven|eight|nine|ten|\d+)"
_DURATION = re.compile(
    rf"""\b(?:
        (?:in|within|inside|under|after|takes?|took|needs?)\s+
        # "takes us about four weeks" — the object pronoun sits between the verb
        # and the count, and without this the most natural phrasing slips past.
        (?:(?:us|it|me|you|them)\s+)?
        (?:just\s+|only\s+|about\s+|around\s+|as\s+little\s+as\s+)?
        {_COUNT}\s*[-\s]?{_DELIVERY_UNITS}
      | \d+\s*-\s*{_DELIVERY_UNITS}\s+(?:turnaround|delivery|build|sprint)
      | same[-\s]day | next[-\s]day | overnight | 24[-\s]?h(?:ou)?rs?
      | by\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday
              |tomorrow|the\s+weekend|end\s+of\s+(?:day|week|month))
    )\b""",
    re.I | re.X,
)

# A duration only matters when it is a duration *of delivering something*.
_DELIVERY_CONTEXT = re.compile(
    r"\b(?:deliver\w*|ship\w*|build\w*|built|launch\w*|prototype|mvp|turnaround|"
    r"ready|done|complete[ds]?|finish\w*|hand\s?over|handover|go\s+live|live|"
    r"up\s+and\s+running|in\s+your\s+hands|start\s+to\s+finish|"
    r"from\s+brief\s+to|first\s+version|working\s+version)\b",
    re.I,
)

# Said outright, these are commitments however they are phrased around.
_HARD_PROMISE = re.compile(
    r"\b(?:guaranteed\s+(?:delivery|turnaround|in|within|by)"
    r"|delivery\s+guarantee"
    r"|\d+\s*[-\s]?(?:hour|day|week)\s+guarantee"
    r"|money[-\s]back\s+if\s+(?:we|it)\s+\w+\s+late)\b",
    re.I,
)

# ── prices ───────────────────────────────────────────────────────────────────
_MONEY = re.compile(
    r"(?:[$£€₹]\s?\d[\d,.]*\s?[kmb]?\b"
    r"|\b\d[\d,.]*\s?[kmb]?\s?(?:usd|gbp|eur|inr|dollars?|pounds?|euros?|rupees?)\b"
    r"|\b(?:four|five|six|seven)[-\s]figures?\b)",
    re.I,
)
# Strong: the sentence is unambiguously pricing something, so an unattributed
# figure beside one is our price by default.
_PRICING_STRONG = re.compile(
    r"\b(?:cost\w*|price[ds]?|pricing|quote[ds]?|quoting|charge[ds]?|charging|"
    r"fees?|retainers?|packages?|budget\w*|invoice[ds]?|bill\w*|"
    r"starts?\s+(?:at|from)|starting\s+(?:at|from)|from\s+just|as\s+little\s+as)\b",
    re.I,
)
# Weak: ordinary words that merely *can* be about pricing. "The commission rate
# falls to 15% for developers earning under $1,000,000" is a fact about someone
# else's business, and treating `rate` as proof of pricing rejected it. These
# only count when the sentence is already about us.
_PRICING_WEAK = re.compile(r"\b(?:rates?|pay|pays|paid|paying|spend\w*|worth|value\s+of)\b", re.I)

_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?", re.M)


def check(text: str) -> list[str]:
    """Reasons this text must not be published. Empty means it passes."""
    reasons: list[str] = []
    if not text or not text.strip():
        return reasons

    for sentence in _sentences(text):
        who = _about(sentence)

        for match in _HARD_PROMISE.finditer(sentence):
            reasons.append(
                f"{match.group(0)!r} is a delivery guarantee. No timeline commitment "
                "for a prototype or a project may be published, in any form."
            )

        if who != "theirs":
            for match in _DURATION.finditer(sentence):
                if not _DELIVERY_CONTEXT.search(sentence):
                    continue
                reasons.append(
                    f"{match.group(0)!r} promises delivery within a time. Describe the "
                    "process without attaching a duration to it - how long a build "
                    "takes always depends on the requirements."
                )
                break

        if who != "theirs":
            pricing = bool(_PRICING_STRONG.search(sentence)) or (
                who == "ours" and bool(_PRICING_WEAK.search(sentence))
            )
            for match in _MONEY.finditer(sentence):
                if not pricing:
                    continue
                reasons.append(
                    f"{match.group(0)!r} states a fixed price. Our cost depends on the "
                    "requirements and is never a number in a post. Comparing how the "
                    "industry prices is fine - attribute it ('most agencies...')."
                )
                break

    # Deduplicate while keeping order: a phrase repeated across a caption and a
    # slide is one problem to fix, and six copies of it in the regeneration note
    # crowds out the other reasons.
    seen: set[str] = set()
    return [r for r in reasons if not (r in seen or seen.add(r))]


def _sentences(text: str) -> list[str]:
    """Sentence-scoped, not window-scoped.

    A character window straddles the boundary between "most agencies charge
    £8,000" and the next sentence about us, and then attributes one to the other.
    Sentences are where attribution actually lives.
    """
    return [s.strip() for s in _SENTENCE.findall(text) if s.strip()]


def _about(sentence: str) -> str:
    """`theirs` only when the sentence attributes the claim elsewhere.

    Note the asymmetry, which is the safe direction: unattributed defaults to
    *not* theirs. A bare "a site like this costs £8,000" published on our own
    account is read by every reader as our price, so it is treated as one.
    """
    if _THEIRS.search(sentence) and not _OURS.search(sentence):
        return "theirs"
    if _OURS.search(sentence):
        return "ours"
    return "unknown"
