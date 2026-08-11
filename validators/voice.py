"""The voice gate — CAMPAIGN.md §3 and §7.2.

Banned phrases plus structural checks. The structural ones matter more than the
word list: a model told to avoid "delve" will avoid "delve" and still write
fifteen consecutive sentences of identical length, which is the strongest
machine-generated signal there is.
"""
from __future__ import annotations

import re
import statistics

from prompts.library import BANNED_PHRASES

# "It's not just X - it's Y" and its variants.
_NOT_JUST = re.compile(r"\b(?:it'?s|this is|that'?s)\s+not\s+just\b", re.I)
# "The result?" / "The catch?" as a one-word rhetorical sentence.
_RHETORICAL_FRAGMENT = re.compile(r"(?:^|[.!?]\s)(?:the\s+\w+\?)(?:\s|$)", re.I)
# Emoji bullet lists, and the rocket specifically.
_EMOJI_BULLET = re.compile(r"^\s*[\U0001F300-\U0001FAFF✀-➿]\s*\S", re.M)
_ROCKET = "\U0001F680"
# "faster, smarter, better" - three adjectives, no substance.
_TRICOLON = re.compile(r"\b(\w+er),\s+(\w+er),?\s+(?:and\s+)?(\w+er)\b", re.I)
# Context-setting throat-clears as an opening.
_THROAT_CLEAR = re.compile(
    r"^\s*(?:in (?:today'?s|the world of|an era)|as (?:a |an )?\w+ (?:owner|founder)"
    r"|nowadays|these days|in recent years|it'?s no secret)",
    re.I,
)


# 0.18 is where genuinely flat prose sits and real writing does not. Measured:
#
#   [4, 8, 6, 6]      24%   "Nine no-shows a week. That is the number the owner
#                            gave us. We looked at the booking page..."  -> good
#   [14, 15, 16, 15]   5%   near-identical lengths                       -> flat
#   [12, 12, 12, 12]   0%   the real signal                              -> flat
def check(text: str, min_variance: float = 4.0, min_variation: float = 0.18) -> list[str]:
    reasons: list[str] = []
    lowered = text.lower()

    for phrase in BANNED_PHRASES:
        if phrase in lowered:
            reasons.append(f"banned phrase: {phrase!r}")

    if _NOT_JUST.search(text):
        reasons.append("uses the \"It's not just X - it's Y\" construction")
    if _RHETORICAL_FRAGMENT.search(text):
        reasons.append("uses a one-word rhetorical fragment like 'The result?'")
    if _EMOJI_BULLET.search(text):
        reasons.append("uses an emoji bullet list")
    if _ROCKET in text:
        reasons.append("contains a rocket emoji")
    if _TRICOLON.search(text):
        reasons.append("tricolon padding (three -er adjectives in a row)")
    if _THROAT_CLEAR.match(text.strip()):
        reasons.append("opens on context rather than on tension")

    sentences = _sentences(text)
    if len(sentences) >= 4:
        lengths = [len(s.split()) for s in sentences]
        spread = statistics.pstdev(lengths)
        mean = statistics.fmean(lengths)
        # Measured RELATIVE to the mean, not as an absolute word count.
        #
        # A flat "stdev >= 4 words" is right for a 200-word LinkedIn post and
        # wrong for a 60-word Facebook one, where it demands a fourteen-word
        # sentence to offset a four-word one. Measured against three real
        # rejections, it was failing copy like:
        #
        #     "The booking page worked. Nobody used it. Six seconds to load on
        #      a phone. No reminder."          -> stdev 1.9, rejected
        #
        # which is the exact voice CAMPAIGN.md §3 asks for. Meanwhile it passed
        # nothing it should have caught: uniform prose has a low coefficient of
        # variation at every length, because that is what uniform means.
        #
        # The absolute spread stays as an escape hatch — long prose with genuine
        # variety can have a modest CV and still obviously vary.
        variation = spread / mean if mean else 0.0
        if variation < min_variation and spread < min_variance:
            reasons.append(
                f"sentence lengths are too uniform (varies {variation:.0%} around a "
                f"{mean:.0f}-word average, wanted {min_variation:.0%}) - uniform "
                "sentence length is the strongest machine-written signal. Write a "
                "four-word sentence, then a longer one that earns its length."
            )
    return reasons


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if len(p.strip().split()) > 1]
