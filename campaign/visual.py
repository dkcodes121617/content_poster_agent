"""The visual vocabulary — CONTENT_SYSTEM.md §3.1 and §3.2 as one registry.

## Why a registry rather than a template with more branches

Before this file existed there was **one deck shape**: cover → statement →
metric → steps → statement → cta, centred, same background, every time. The
prompt already asked for variety and that is what it produced, which is the
whole argument: variety cannot come from asking. It has to be structural.

Three independent axes multiply instead of adding:

    archetype (20) x layout (5) x theme (3)

The registry is the contract. Four things read it and none of them may hold a
second opinion:

  * `validators/slides.py` — is this slide renderable, and does it fit?
  * `prompts/library.py`   — what shape of JSON to ask the writer for
  * `templates/slide.html` — how to draw it
  * `campaign/recipes.py`  — which archetypes may follow which

A new archetype is a row here, a builder in the template and a CSS block. It is
never a special case in the write node.

## The budgets are a quality gate, not a safety net

The template auto-shrinks text that would overflow (see `fit()` in slide.html),
so nothing can render broken. That is the safety net. These budgets are a
different thing: they reject copy that would *only* fit after shrinking, because
a cover headline rendered at 60% of its intended size is technically correct and
visibly wrong. The writer gets told to write shorter; the renderer never has to.

Measured against the 1080px canvas with the real fonts — see
`tests/test_slides_validator.py::test_budgets_match_measured_capacity`, which
renders each field at its budget and asserts it needs no shrinking.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ── Themes ───────────────────────────────────────────────────────────────────
# `tinted` is new: the baby-blue wash as a full background rather than a
# top-corner gradient. Dark/light alone made every deck alternate between two
# states, which reads as a toggle rather than a palette.
THEMES = ("dark", "light", "tinted")

# ── Layouts (§3.2) ───────────────────────────────────────────────────────────
# The second axis. Independent of archetype, and cheap: one CSS block each,
# changing how every archetype composes rather than adding new ones.
LAYOUTS = ("centred", "top_anchored", "split_5050", "full_bleed", "offset_grid")


@dataclass(frozen=True)
class Archetype:
    name: str
    family: str
    # Fields the template needs to draw anything at all. A slide missing one of
    # these is rejected pre-render rather than producing an empty box.
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    # Layouts this archetype composes correctly in. `full_bleed` needs artwork;
    # `split_5050` needs two things to put side by side. Restricting here is what
    # lets the rotation ledger pick a layout at random and always be right.
    layouts: tuple[str, ...] = ("centred",)
    themes: tuple[str, ...] = THEMES
    # Reads a `chart` object and must have its numbers grounded (§3.5).
    charted: bool = False
    # Embeds artwork from the site repo. Degrades to `fallback` when the slug
    # has no graphic — 7 of 26 projects do not (verified against the manifest).
    imaged: bool = False
    fallback: str = ""
    brief: str = ""
    _budgets: dict[str, int] = field(default_factory=dict)

    def budgets(self) -> dict[str, int]:
        return {**FIELD_BUDGETS, **self._budgets}


# Characters per field, before the renderer would have to shrink anything.
# Derived from the type scale in brand.css against the 896px usable width of the
# 1080px canvas, then verified by measurement.
FIELD_BUDGETS: dict[str, int] = {
    "kicker": 28,
    "title": 90,        # h2 — three lines
    "body": 200,        # four lines at 88% width
    "value": 10,        # the metric. One line, or it is not a metric.
    "label": 60,
    "quote": 190,
    "attribution": 60,
    "pill": 40,
    "note": 90,
    "caption": 110,
    "myth": 110,
    "fact": 130,
    "step_title": 60,
    "step_detail": 90,
    "item": 78,         # checklist row
    "node": 26,         # a flow-diagram box
    "stat_value": 8,
    "stat_label": 34,
    # 26, not 22. The label column is 26% of the 896px content width at ~30px
    # type, so it takes ~13 characters a line over two lines. 22 rejected
    # "Working prototype first" (23) and "Paid discovery phase, then a quote"
    # in three separate runs, all of them legitimate bar labels.
    "series_label": 26,
}

# h1 is far larger than h2, so the opener families get a tighter title budget.
_COVER = {"title": 42, "body": 150}


ARCHETYPES: tuple[Archetype, ...] = (
    # ── Openers ──────────────────────────────────────────────────────────────
    Archetype(
        "cover_bold", "opener", required=("title",), optional=("kicker", "body"),
        layouts=("centred", "top_anchored", "offset_grid"), _budgets=_COVER,
        brief="A flat declarative hook. Six words maximum. The only slide most people see.",
    ),
    Archetype(
        "cover_question", "opener", required=("title",), optional=("kicker", "body"),
        layouts=("centred", "top_anchored", "offset_grid"), _budgets=_COVER,
        brief="Open on a question the reader has already asked themselves. Ends in '?'.",
    ),
    Archetype(
        "cover_stat", "opener", required=("value", "label"), optional=("kicker", "body"),
        layouts=("centred", "top_anchored"), _budgets=_COVER,
        brief="A single number as the hook, with the label beneath it doing the explaining.",
    ),
    Archetype(
        "cover_mockup", "opener", required=("title", "image"), optional=("kicker",),
        layouts=("split_5050", "full_bleed", "top_anchored"), imaged=True,
        fallback="cover_bold", _budgets=_COVER,
        brief="Artwork from a real project behind the headline. Show the work first.",
    ),

    # ── Data ─────────────────────────────────────────────────────────────────
    Archetype(
        "metric_hero", "data", required=("value", "label"), optional=("kicker", "body"),
        layouts=("centred", "top_anchored", "offset_grid"),
        brief="One number, enormous. Never two: a slide with two numbers has neither.",
    ),
    Archetype(
        "stat_row", "data", required=("stats",), optional=("kicker", "title"),
        layouts=("centred", "top_anchored"),
        brief="Exactly three tiles, each one value and one label. The site's own 30/11/100% row.",
    ),
    Archetype(
        "bar_chart", "data", required=("title", "chart"), optional=("kicker", "body"),
        layouts=("centred", "top_anchored"), charted=True,
        brief="Three to five horizontal bars. Every value must come from the curated stats.",
    ),
    Archetype(
        "comparison_bar", "data", required=("title", "chart"), optional=("kicker", "note"),
        layouts=("centred", "top_anchored"), charted=True,
        brief="Exactly two bars, us against the alternative. The contrast is the point.",
    ),
    Archetype(
        "donut", "data", required=("title", "chart"), optional=("kicker", "body"),
        layouts=("centred", "top_anchored"), charted=True,
        brief="One percentage as a ring. Use when the number is a share of something.",
    ),

    # ── Explainers ───────────────────────────────────────────────────────────
    Archetype(
        "statement", "explainer", required=("title",), optional=("kicker", "body"),
        layouts=("centred", "top_anchored", "offset_grid"),
        brief="One idea, said plainly. The connective tissue of a deck.",
    ),
    Archetype(
        "steps", "explainer", required=("title", "steps"), optional=("kicker",),
        layouts=("centred", "top_anchored"),
        brief="Three or four numbered cards, each a title and a short detail.",
    ),
    Archetype(
        "checklist", "explainer", required=("title", "items"), optional=("kicker",),
        layouts=("centred", "top_anchored"),
        brief="Four or five ticked lines. Things to check, not things to do in order.",
    ),
    Archetype(
        "flow_diagram", "explainer", required=("title", "nodes"), optional=("kicker", "body"),
        layouts=("centred", "top_anchored"),
        brief="Three to five boxes with arrows between them. Each box is two or three words.",
    ),
    Archetype(
        "before_after", "explainer", required=("title", "before", "after"), optional=("kicker",),
        layouts=("centred", "top_anchored"),
        brief="Two panels. What it was, what it became. Concrete on both sides.",
    ),
    Archetype(
        "myth_fact", "explainer", required=("myth", "fact"), optional=("kicker",),
        layouts=("centred", "offset_grid"),
        brief="A belief a buyer holds, struck through, then what is actually true.",
    ),

    # ── Proof ────────────────────────────────────────────────────────────────
    Archetype(
        "mockup_browser", "proof", required=("title", "image"), optional=("kicker", "url"),
        layouts=("centred", "top_anchored", "full_bleed"), imaged=True,
        fallback="statement",
        brief="Browser chrome around real project artwork. Depicting real software.",
    ),
    # `mockup_phone` was dropped once and is back, and the reason is the whole
    # argument for generating artwork instead of looking it up.
    #
    # It was removed because every asset in the library was landscape — project
    # cards and blog diagrams authored for a blog column — so a portrait phone
    # frame could only letterbox or crop them. Mockups are now DRAWN
    # (imaging/mockups.py), so a portrait canvas is simply another function, and
    # ten of twenty-six projects are mobile apps that were being shown in
    # browser chrome. `decorate()` swaps browser for phone when the project is
    # a mobile build.
    Archetype(
        "mockup_phone", "proof", required=("title", "image"), optional=("kicker",),
        layouts=("split_5050", "centred"), imaged=True, fallback="statement",
        brief="A phone frame around the app's own screen. Mobile builds only.",
    ),
    Archetype(
        "graphic_embed", "proof", required=("image",), optional=("kicker", "title", "caption"),
        # No `full_bleed`: a diagram behind the scrim that makes overlaid text
        # readable is itself unreadable, and the diagram is the whole slide.
        # Decorative artwork bleeds; information does not.
        layouts=("centred", "top_anchored"), imaged=True,
        fallback="statement",
        brief="A diagram drawn for the blog, reused whole. The caption comes from the repo.",
    ),
    Archetype(
        "quote", "proof", required=("quote", "attribution"), optional=("kicker",),
        layouts=("centred", "offset_grid"),
        brief="A client's words as a sentence. Verbatim from a real testimonial, never reworded.",
    ),

    # ── Closers ──────────────────────────────────────────────────────────────
    Archetype(
        "cta_pill", "closer", required=("title", "pill"), optional=("body",),
        layouts=("centred", "top_anchored"), _budgets=_COVER,
        brief="Closes the deck. The offer, then the URL as a pill.",
    ),
    Archetype(
        "cta_split", "closer", required=("title", "pill"), optional=("body", "note"),
        layouts=("split_5050", "centred"), _budgets=_COVER,
        brief="Closes the deck with the offer on one side and the next step on the other.",
    ),
)

BY_NAME: dict[str, Archetype] = {a.name: a for a in ARCHETYPES}

# The seven original roles. Decks generated before the registry existed, the
# `--force` path and `_fallback_slide` all still speak this vocabulary, and
# breaking them would mean a rebuild produces something different from what was
# reviewed. Aliases are resolved on the way in, once, in `resolve()`.
LEGACY_ROLES: dict[str, str] = {
    "cover": "cover_bold",
    "metric": "metric_hero",
    "mockup": "mockup_browser",
    "cta": "cta_pill",
}

FAMILIES = ("opener", "data", "explainer", "proof", "closer")


def resolve(role: str) -> Archetype | None:
    """The archetype for a slide's `role`, honouring legacy names."""
    key = (role or "").strip()
    return BY_NAME.get(LEGACY_ROLES.get(key, key))


def by_family(family: str) -> list[Archetype]:
    return [a for a in ARCHETYPES if a.family == family]


def names(family: str = "") -> list[str]:
    return [a.name for a in ARCHETYPES if not family or a.family == family]


def layouts_for(role: str) -> tuple[str, ...]:
    a = resolve(role)
    return a.layouts if a else ("centred",)


def is_charted(role: str) -> bool:
    a = resolve(role)
    return bool(a and a.charted)


def is_imaged(role: str) -> bool:
    a = resolve(role)
    return bool(a and a.imaged)


def fallback_for(role: str) -> str:
    """What to render instead when an imaged archetype has no artwork.

    Never an empty frame. Seven of the twenty-six projects have no graphic in
    the site manifest, so this path is ordinary rather than exceptional, and a
    slide that quietly renders a grey box is worse than one that renders a
    sentence.
    """
    a = resolve(role)
    return (a.fallback if a else "") or "statement"
