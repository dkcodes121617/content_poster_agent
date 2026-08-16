"""Deck planning — one place that decides what a carousel looks like.

The write node and `tools/showcase.py` both call this, and that is the whole
point of it existing as a module. The showcase is the only honest preview this
system has; the moment it assembles decks its own way it stops proving anything
about the code that publishes.

Two phases, either side of the model:

    plan()      before writing — pick the recipe, the archetypes, the layouts,
                the themes and the region. The writer is told the shape; it does
                not choose it.

    decorate()  after writing — attach theme, layout and real artwork to what
                came back, and downgrade any archetype whose artwork is missing.

The split matters. Everything in `plan()` has to be decided before the prompt is
built, and everything in `decorate()` needs the model's output to exist. Doing
either in the wrong half was how the first version ended up asking the model for
an `image` field and then overwriting it.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import date

from campaign import capacity, keywords, phase, recipes, regions, visual
from campaign.calendar import today_ist

log = logging.getLogger("content_poster.deck")


@dataclass
class DeckPlan:
    platform: str
    pillar: str
    recipe: str
    archetypes: list[str] = field(default_factory=list)
    layouts: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    region: regions.Region = regions.DEFAULT
    phase_name: str = "full"
    # Set when the calendar's pillar was withheld by the current phase.
    substituted_from: str = ""
    # The search phrase the opening line is written to carry. On LinkedIn and
    # dev.to that line also becomes the post's URL slug.
    phrase: keywords.Phrase | None = None

    def brief(self) -> str:
        shape = " -> ".join(self.archetypes)
        kw = f' "{self.phrase.text}"' if self.phrase else ""
        return f"{self.recipe} [{shape}] {self.region.code}{kw}"


def plan(
    config,
    *,
    platform: str,
    pillar: str,
    slides: int,
    hour_ist: int = 0,
    snapshot=None,
    library=None,
    today: date | None = None,
    history: list[dict] | None = None,
    recipe: str = "",
) -> DeckPlan:
    """Everything about a deck that is decided before a word is written.

    `recipe` overrides the rotation ledger's choice. It exists for `tools/e2e.py`
    and `--force`, where the point is to exercise a named recipe rather than
    whatever variety says is due — the ledger's job is to stop a human choosing,
    and a test that cannot choose cannot cover all eight.
    """
    today = today or today_ist()
    start = config.start_date()

    # Phasing first: substituting the pillar changes which recipes are eligible,
    # so doing it after would pick a recipe for a pillar that never runs.
    effective_pillar = phase.substitute(pillar, start, today)
    current_phase = phase.current(start, today)

    region = (
        regions.for_slot(platform, hour_ist, today) if config.geo_targeting else regions.DEFAULT
    )
    if region.code not in [r.upper() for r in config.regions_enabled]:
        region = regions.get(next(iter(config.regions_enabled), "US"))

    if not config.visual_variety:
        # The original single deck shape, kept reachable so the new system can
        # be compared against the old one rather than only asserted better.
        shape = recipes.BY_NAME[recipes.FALLBACK]
        archetypes = recipes.fit_to_length(shape, slides)
        return DeckPlan(
            phrase=keywords.pick(effective_pillar, platform=platform,
                                 region=region.code, today=today)
            if config.seo_phrases else None,
            platform=platform, pillar=effective_pillar, recipe=shape.name,
            archetypes=archetypes, layouts=["centred"] * len(archetypes),
            themes=recipes.apply_themes(archetypes, "light"),
            region=region, phase_name=current_phase.name,
            substituted_from=pillar if effective_pillar != pillar else "",
        )

    has_stats = bool(
        config.charts_enabled and snapshot is not None and snapshot.chartable_stats()
    )
    # Only `graphic_embed` can be blocked by missing artwork: mockups are
    # generated, so a project without a card in the site manifest is no longer
    # a project we cannot picture.
    has_art = bool(
        config.site_artwork and library is not None and library.manifest().get("charts")
    )

    if recipe and recipe in recipes.BY_NAME:
        import random as _random

        chosen = recipes.BY_NAME[recipe]
        archetypes = recipes.fit_to_length(chosen, slides)
        rng = _random.Random(f"{today.isoformat()}:{platform}:{effective_pillar}")
        layouts = [rng.choice(list(visual.layouts_for(a))) for a in archetypes]
        middle_theme = rng.choices(("light", "tinted"), weights=(0.68, 0.32))[0]
    else:
        chosen, archetypes, layouts, middle_theme = recipes.pick(
            config, platform=platform, pillar=effective_pillar, slides=slides,
            has_stats=has_stats, has_art=has_art, today=today, history=history,
        )
    phrase = keywords.pick(
        effective_pillar, platform=platform, region=region.code, today=today,
        used=[r.get("phrase") for r in (history or []) if r.get("phrase")],
    ) if config.seo_phrases else None

    return DeckPlan(
        phrase=phrase,
        platform=platform,
        pillar=effective_pillar,
        recipe=chosen.name,
        archetypes=archetypes,
        layouts=layouts,
        themes=recipes.apply_themes(archetypes, middle_theme),
        region=region,
        phase_name=current_phase.name,
        substituted_from=pillar if effective_pillar != pillar else "",
    )


def decorate(
    slides: list[dict],
    deck: DeckPlan,
    *,
    library=None,
    snapshot=None,
    rng: random.Random | None = None,
) -> list[dict]:
    """Attach role, theme, layout and artwork to what the model returned.

    The model is told which archetype each slide is and writes the words for it.
    Everything visual is applied here, because a layout chosen by the writer is
    a field that can be wrong in a way no upstream validator would catch — and
    the registry already knows which layouts each archetype composes in.

    An imaged archetype whose artwork cannot be found is **downgraded**, not
    left with a broken frame. Seven of twenty-six projects have no graphic in
    the site manifest, so this path is ordinary rather than exceptional.
    """
    rng = rng or random.Random(f"{deck.platform}:{deck.pillar}:{deck.recipe}")
    out: list[dict] = []

    for i, raw in enumerate(slides):
        if not isinstance(raw, dict):
            continue
        slide = dict(raw)
        # The plan is authoritative on role. A model that returned the roles in
        # a different order, or renamed one, would otherwise silently publish a
        # deck with a shape the rotation ledger never recorded.
        role = deck.archetypes[i] if i < len(deck.archetypes) else slide.get("role", "statement")
        slide["role"] = role

        if visual.is_imaged(role):
            role = _frame_for(role, slide, snapshot)
            slide["role"] = role
            art = _artwork_for(role, slide, library, snapshot, rng)
            if art:
                slide["svg"] = art.svg
                # Recorded so a review can answer "which artwork was this?"
                # without reading 6 KB of markup. The mismatch that shipped —
                # a Cine Duniya card under a headline about a solar
                # marketplace — was invisible in the report for exactly this
                # reason.
                slide["_art"] = art.file
                # A diagram's caption is written in the repo, about a real post.
                # Preferring it over the model's is not pedantry: it makes the
                # slide grounded by construction.
                if art.caption and role == "graphic_embed":
                    slide["caption"] = art.caption
                slide.pop("image", None)
            else:
                fallback = visual.fallback_for(role)
                log.info("no artwork for %s; falling back to %s", role, fallback)
                slide["role"] = fallback
                role = fallback
                slide.pop("image", None)
                slide.pop("svg", None)
                slide.pop("caption", None)
                _fill_required(slide, fallback)

        slide["theme"] = deck.themes[i] if i < len(deck.themes) else "light"
        wanted = deck.layouts[i] if i < len(deck.layouts) else ""
        allowed = visual.layouts_for(role)
        slide["layout"] = wanted if wanted in allowed else allowed[0]
        out.append(slide)

    return out


def _artwork_for(role: str, slide: dict, library, snapshot, rng: random.Random):
    """Artwork for an imaged slide, or None.

    ## Mockups are drawn, diagrams are looked up

    `mockup_browser` and `cover_mockup` get a **generated** mockup (see
    `imaging/mockups.py`), chosen from the project's own category and tech. That
    removes an entire class of failure: there is no longer any such thing as a
    project with no artwork, so there is no fallback that could reach for
    somebody else's. The version that did produced "Solar marketplace. Live in
    India." above a card reading *Cine Duniya — ENTERTAINMENT*.

    `graphic_embed` still looks up a real blog diagram, because that archetype's
    whole point is reusing a diagram we actually drew, and its caption comes
    from the repo.
    """
    from imaging import mockups
    from imaging.graphics import Artwork

    try:
        if role == "graphic_embed":
            return library.diagram(rng=rng) if library is not None else None
        project = _named_project(slide, snapshot)
        mock = mockups.for_project(project) if project else mockups.by_kind(
            _kind_from_text(slide)
        )
        return Artwork(
            file=f"mockup:{mock.kind}", svg=mock.svg, kind="mockup",
            alt=f"An illustration of {mock.describes}",
            source_slug=getattr(project, "slug", "") or "",
        )
    except Exception:
        # Artwork is an enhancement. A failure here degrades the slide to text;
        # it does not fail the run.
        log.warning("artwork lookup failed for %s", role, exc_info=True)
        return None


def _frame_for(role: str, slide: dict, snapshot) -> str:
    """Browser or phone, decided by the shape of the mockup that will go in it.

    A mobile app drawn on a phone-shaped canvas and then wrapped in browser
    chrome is a small lie about what was built, and ten of twenty-six projects
    are mobile. The recipe names `mockup_browser` because that is the common
    case; the frame is corrected here, where the project is known.
    """
    from imaging import mockups

    if role not in ("mockup_browser", "mockup_phone"):
        return role
    project = _named_project(slide, snapshot)
    kind = (
        mockups.for_project(project).kind if project else _kind_from_text(slide)
    )
    return "mockup_phone" if kind in mockups.PORTRAIT else "mockup_browser"


def _named_project(slide: dict, snapshot):
    """The project this slide is actually about, or None.

    Matched by name or by slug in the URL, and **never guessed**. Returning None
    is the safe answer: the caller then draws a mockup from the words on the
    slide rather than from a project nobody mentioned. Guessing is what put a
    gaming app under a headline about voice AI.
    """
    if snapshot is None:
        return None
    text = " ".join(
        str(slide.get(k) or "") for k in ("title", "body", "kicker", "caption", "url")
    ).lower()
    for project in snapshot.projects:
        if project.name and project.name.lower() in text:
            return project
        if project.slug and f"/work/{project.slug}" in text:
            return project
    return None


def _kind_from_text(slide: dict) -> str:
    """A mockup kind read off the slide's own words, when no project is named.

    A `mockup_browser` on a teaching post is illustrating an idea, not a
    project, so the picture should follow the idea. "How a booking page should
    work" draws a calendar; anything unrecognised draws a dashboard.
    """
    from imaging import mockups

    return mockups.kind_for(description=" ".join(
        str(slide.get(k) or "") for k in ("title", "body", "kicker", "caption")
    ))


def _fill_required(slide: dict, role: str) -> None:
    """Give a downgraded slide the fields its new archetype needs.

    A `cover_mockup` losing its artwork becomes a `cover_bold`, which needs only
    a title it already has. A `mockup_browser` becomes a `statement`, same. This
    exists for the case where it does not: rather than emit a slide the
    pre-render gate will reject, borrow from what is present.
    """
    arche = visual.resolve(role)
    if not arche:
        return
    for name in arche.required:
        if slide.get(name):
            continue
        if name == "title":
            slide["title"] = slide.get("caption") or slide.get("kicker") or "How we build"
        elif name == "body":
            slide["body"] = slide.get("caption", "")


def hashtags(config, deck: DeckPlan, count: int, today: date | None = None) -> list[str]:
    """Regional tags for this deck, or [] when geo targeting is off.

    `count` is what the writer produced, and it is only a starting point. The
    platform decides how many are actually acceptable, and substituting one for
    one meant a five-tag draft became five regional tags on a platform that
    requires eight — a geography feature failing a platform gate, which is the
    worst kind of interaction because neither side looks wrong on its own.
    """
    if not config.geo_targeting:
        return []

    # Threads takes exactly ONE tag and treats it as a TOPIC, not a hashtag: it
    # is the feed the post joins. A regional tag like "EUTech" or "TechEurope"
    # is a topic almost nobody reads, so the post lands in a room with no one
    # in it — which is what a live account showed after a day of posting.
    #
    # The regional bank is right for Instagram, where tags are discovery
    # keywords and eleven of them cost nothing. It is wrong here. On Threads
    # the only question is which existing conversation is worth joining.
    if deck.platform == "threads":
        return [_threads_topic(deck)]

    from validators.platform import LIMITS

    limits = LIMITS.get(deck.platform)
    if limits:
        _, _, _, min_tags, max_tags = limits
        if max_tags <= 0:
            return []          # this platform takes none at all
        count = max(count, min_tags)
        count = min(count, max_tags)
    if count <= 0:
        return []
    return regions.hashtags_for(deck.region, deck.platform, deck.pillar, count, today)


# Threads topics with real traffic, by what the post is about. Deliberately
# broad: a topic is a room, and the point is to walk into a busy one. Anything
# narrower than these is a room we would be standing in alone.
_THREADS_TOPICS = {
    "proof": "SmallBusiness",
    "client_voice": "SmallBusiness",
    "teach": "Entrepreneurship",
    "process": "Entrepreneurship",
    "direct_offer": "Entrepreneurship",
    "pov": "Tech",
    "timely": "AI",
}


def _threads_topic(deck: DeckPlan) -> str:
    """The one topic tag a Threads post carries.

    Chosen from the pillar rather than the region, because a Threads topic is
    not a targeting parameter — it is which conversation the post joins, and
    "UK small business owners" is not a conversation that exists there.
    """
    return _THREADS_TOPICS.get(deck.pillar, "SmallBusiness")


def record(config, deck: DeckPlan, run_id: str = "") -> None:
    recipes.record(
        config,
        platform=deck.platform, pillar=deck.pillar, recipe=deck.recipe,
        archetypes=deck.archetypes, layouts=deck.layouts,
        theme=deck.themes[1] if len(deck.themes) > 1 else "",
        region=deck.region.code, run_id=run_id,
    )


def capacity_allows(config, platform: str, today: date | None = None) -> bool:
    """Whether the posting plan has room for another post today.

    Off by default. The fixed weekly calendar governs volume perfectly well
    until a platform actually unlocks, and a second scheduler running alongside
    it is a second thing that can silently stop the agent posting.
    """
    if not config.capacity_scheduling:
        return True
    return capacity.has_capacity(config, platform, today)
