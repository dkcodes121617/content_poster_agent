"""The opening-line gate: is this post findable?

On LinkedIn and dev.to the first words of a post become its public URL:

    linkedin.com/posts/wizcodes_free-prototype-before-hiring-a-developer-activity-7…
    dev.to/wizcodes/what-software-development-actually-costs-4h2b

That URL sits on a domain with vastly more authority than wizcodes.site will
have for years, and it is crawled. So the opening line is doing two jobs at
once — it is the hook a human reads, and it is the address a search engine
indexes.

## Why this is a gate and not just a prompt line

Because the failure is invisible. A post whose first line missed the phrase
reads perfectly well; nothing about it looks wrong; it simply gets a URL nobody
will ever search for, and you find out never. That is exactly the shape of
defect a validator exists for.

## Why it is not required everywhere

`SEO_PHRASE_REQUIRED` defaults to `linkedin,devto` — the two platforms where the
first line is genuinely a URL. On Threads or Instagram the phrase is still worth
having for on-platform search, but it is a preference, and **a preference should
not cost a slot**. Rejecting a good Threads post over a keyword would be the
tail wagging the dog.

## What it deliberately does not check

That the phrase appears verbatim. The natural sentence almost never is the
phrase — "most founders start by comparing a freelancer vs an agency vs a
studio" has to satisfy "freelancer vs agency vs studio", or the check would
force precisely the robotic phrasing that makes a post read as spam. Matching is
on content words, two thirds of them, inside the opening fourteen.
"""
from __future__ import annotations

from campaign import keywords

# Superlatives we cannot substantiate. These are the shapes a model reaches for
# when told to write something "searchable", and every one of them is both
# unprovable and the reason a reader stops trusting an account.
_UNPROVABLE = (
    "best", "#1", "number one", "no.1", "top rated", "top-rated", "leading",
    "world class", "world-class", "unbeatable", "unmatched", "premier",
    "most trusted", "award winning", "award-winning",
)


def check(
    caption: str,
    phrase: keywords.Phrase | None,
    platform: str,
    required: list[str] | None = None,
    pillar: str = "",
) -> list[str]:
    """Reasons this post is not findable. Empty means it passes."""
    reasons: list[str] = []
    if not caption or not caption.strip():
        return reasons

    opening = _first_line(caption)
    lowered = opening.lower()

    # Checked on every platform, phrase or no phrase. A superlative about
    # ourselves is a claim we cannot evidence, and it is the exact sentence
    # somebody writes when they are aiming at a keyword rather than a reader.
    for word in _UNPROVABLE:
        if f" {word} " in f" {lowered} " or lowered.startswith(f"{word} "):
            reasons.append(
                f"the opening line claims to be {word!r} - a superlative we cannot "
                "evidence. Open on something checkable: what we do, or what the "
                "reader is trying to work out."
            )
            break

    if not phrase or platform not in (required or []):
        return reasons
    if pillar == "timely":
        # A timely post's opening belongs to the news angle. Forcing a keyword
        # into it would either bend the reaction or cost the slot, and a
        # reaction posted three days late is worthless - that is the entire
        # point of having a trend layer.
        return reasons

    if not keywords.in_opening(opening, phrase.text):
        reasons.append(
            f"the opening line does not carry the search phrase "
            f"{phrase.text!r}. On {platform} those first words become the post's "
            f"URL - as written it would be "
            f"'{keywords.slug_preview(opening)}'. Rewrite the first sentence so "
            "the phrase is in it naturally; do not append it."
        )
    return reasons


def _first_line(caption: str) -> str:
    """The opening sentence or line, whichever comes first.

    Both matter: a line break ends the slug just as a full stop does, and the
    writer uses single-line openers deliberately.
    """
    line = caption.strip().split("\n", 1)[0].strip()
    for stop in (". ", "! ", "? "):
        if stop in line:
            line = line.split(stop, 1)[0] + stop[0]
            break
    return line
