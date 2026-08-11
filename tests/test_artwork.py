"""Artwork, mockups and the defects a review of real output turned up.

The one that matters: six imaged slides in a review run, six carrying another
project's card. "Solar marketplace. Live in India." above *Cine Duniya —
ENTERTAINMENT*. "CuePilot: real-time voice AI" above *Bubble.IO — GAMING*. Every
word on those slides was true, so no content gate could see it.
"""
from __future__ import annotations

import pytest

from campaign import deck, visual
from imaging import mockups
from platforms import Draft


def plan_for(role: str, **kw) -> deck.DeckPlan:
    return deck.DeckPlan(
        platform="instagram", pillar="proof", recipe="proof_narrative",
        archetypes=[role], layouts=[visual.layouts_for(role)[0]], themes=["light"], **kw
    )


# ── the mismatch, gone by construction ───────────────────────────────────────
def test_a_slide_naming_no_project_never_borrows_one(snapshot):
    """The exact failure: artwork chosen at random when nothing was identified."""
    slide = {"title": "Solar marketplace. *Live* in India.",
             "url": "wizcodes.site/work/solarsathi"}
    out = deck.decorate([slide], plan_for("mockup_browser"), library=None, snapshot=snapshot)
    # SolarSathi is not in the test snapshot, so nothing may be attributed to it.
    assert deck._named_project(slide, snapshot) is None
    # It still gets a picture — a generated one, chosen from its own words.
    assert out[0].get("svg"), "expected a generated mockup, not an empty slide"
    assert out[0]["_art"].startswith("mockup:")


def test_a_named_project_gets_its_own_mockup(snapshot):
    slide = {"title": "CuePilot answers in *under 200ms*.",
             "url": "wizcodes.site/work/cuepilot"}
    project = deck._named_project(slide, snapshot)
    assert project is not None and project.slug == "cuepilot"
    out = deck.decorate([slide], plan_for("mockup_browser"), library=None, snapshot=snapshot)
    assert out[0]["_art"] == f"mockup:{mockups.for_project(project).kind}"


def test_a_project_is_matched_by_slug_in_the_url(snapshot):
    slide = {"title": "Shift planning that works", "url": "wizcodes.site/work/rotamatic"}
    assert deck._named_project(slide, snapshot).slug == "rotamatic"


def test_the_same_project_always_draws_the_same_product(snapshot):
    """Two posts about one project must not show two different pieces of software."""
    project = snapshot.projects[0]
    assert mockups.for_project(project).kind == mockups.for_project(project).kind


def test_mockups_carry_no_text_at_all():
    """A picture with no words in it cannot make a claim that turns out false."""
    for name in mockups.KINDS:
        svg = mockups.by_kind(name).svg
        assert "<text" not in svg and "<tspan" not in svg, name


def test_every_mockup_declares_a_viewbox():
    for name in mockups.KINDS:
        assert "viewBox=" in mockups.by_kind(name).svg, name


# ── the frame follows the software ───────────────────────────────────────────
@pytest.mark.parametrize(
    ("category", "tech", "expect_portrait"),
    [("mobile", "Flutter", True), ("web", "Next.js", False),
     ("ai", "Python", False), ("game", "Unity", False)],
)
def test_mobile_builds_get_a_phone_not_a_browser(category, tech, expect_portrait):
    kind = mockups.kind_for(category=category, tech=tech, name="Thing", description="a thing")
    assert (kind in mockups.PORTRAIT) is expect_portrait, kind


def test_decorate_swaps_the_frame_for_a_mobile_project(snapshot):
    """The recipe says `mockup_browser`; a mobile app must still get a phone."""
    slide = {"title": "Rotamatic in a thumb tap"}       # Rotamatic is Flutter
    out = deck.decorate([slide], plan_for("mockup_browser"), library=None, snapshot=snapshot)
    assert out[0]["role"] == "mockup_phone"


def test_decorate_keeps_the_browser_for_a_web_project(snapshot):
    slide = {"title": "CuePilot answers fast"}          # Next.js
    out = deck.decorate([slide], plan_for("mockup_browser"), library=None, snapshot=snapshot)
    assert out[0]["role"] == "mockup_browser"


def test_an_ai_product_about_games_is_a_conversation():
    """Category outranks a keyword: "AI Game Guide" is an assistant."""
    assert mockups.kind_for(category="ai", name="AI Game Guide",
                            description="answers player questions") == "conversation"


def test_a_game_is_a_game_not_a_dashboard():
    assert mockups.kind_for(category="game", name="Jungle Jump",
                            description="a platformer") == "game"


# ── truncation ───────────────────────────────────────────────────────────────
def test_the_single_image_fallback_never_cuts_mid_sentence():
    """A published slide read "Because requirements d". It was a [:180] slice."""
    from graph.nodes import _fallback_slide

    caption = (
        "Most agencies bill discovery as a paid phase. We build a working prototype "
        "before any money changes hands. Not a slideshow. A prototype you can click "
        "through, test with users, and show investors. Why? Because requirements do "
        "not survive first contact with a real screen."
    )
    slide = _fallback_slide(Draft(platform="facebook", pillar="pov", caption=caption))
    for field in ("title", "body"):
        text = slide[field].strip()
        if text:
            assert text[-1] in ".!?", f"{field} ends mid-sentence: {text[-40:]!r}"


def test_the_fallback_prefers_nothing_to_half_a_sentence():
    from graph.nodes import _fallback_slide

    caption = "A single enormous sentence that runs on well past any sensible budget " * 6
    slide = _fallback_slide(Draft(platform="facebook", pillar="pov", caption=caption))
    assert slide["body"] == "" or slide["body"].rstrip()[-1] in ".!?"


def test_the_fallback_slide_passes_the_pre_render_gate():
    from graph.nodes import _fallback_slide
    from validators import slides as gate

    for caption in (
        "Short one.",
        "Most agencies bill discovery as a paid phase. We build a prototype first.",
        "No punctuation at all just a long stream of words that keeps going and going",
    ):
        slide = _fallback_slide(Draft(platform="facebook", pillar="proof", caption=caption))
        assert gate.check([slide]) == [], (caption, gate.check([slide]))
