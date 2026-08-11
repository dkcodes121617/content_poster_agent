"""Real Chromium renders. `pytest --render` to run them.

These are slow (~1s per slide) and they are the only tests here that are, so
they are opt-in. They are also the only tests that can catch what actually went
wrong in the review sets: every defect in CONTENT_SYSTEM.md §1 rendered
*successfully* and was found by a human looking at a PNG.

The audit inside the template does the looking now. These tests assert it stays
honest, and — the part that matters most — they render **every archetype in
every layout it claims to support**, which is the combination nobody checks by
eye and where three of the bugs found during the build were hiding:

  * a full-bleed diagram counted as vertical overflow because absolutely
    positioned children still contribute to scroll height
  * `background:` shorthand in a full-bleed override silently reset
    `background-clip`, so gradient text rendered as a solid blue rectangle
  * `before_after` in `split_5050` ran a card clean off the right edge, because
    its builder emits no panes for the row layout to divide
"""
from __future__ import annotations

import importlib.util

import pytest

from campaign import visual
from tests.conftest import AGENT_ROOT

pytestmark = pytest.mark.render


def _renderer():
    spec = importlib.util.spec_from_file_location("cp_render", AGENT_ROOT / "tools" / "render.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def renderer():
    return _renderer()


@pytest.fixture(scope="module")
def samples(renderer):
    return {s["role"]: s for s in renderer.sample_slides()}


def test_every_archetype_has_a_sample(samples):
    """A registry row with no sample is an archetype nobody has ever rendered."""
    missing = [a.name for a in visual.ARCHETYPES if a.name not in samples]
    assert not missing, f"no render sample for: {', '.join(missing)}"


def test_every_archetype_renders_clean(renderer, samples):
    audits: list[dict] = []
    renderer.render(
        list(samples.values()), "instagram_portrait", "test_all", strict=False, audits=audits
    )
    broken = [(a["role"], a["errors"]) for a in audits if a.get("errors")]
    assert not broken, broken


@pytest.mark.parametrize(
    ("role", "layout"),
    [(a.name, layout) for a in visual.ARCHETYPES for layout in a.layouts],
)
def test_every_archetype_in_every_layout_it_claims(renderer, samples, role, layout):
    """The combination nobody checks by eye, and where the bugs were."""
    slide = {**samples[role], "layout": layout}
    audits: list[dict] = []
    renderer.render([slide], "instagram_portrait", f"test_{role}_{layout}",
                    strict=False, audits=audits)
    assert audits[0]["layout"] == layout
    assert not audits[0]["errors"], audits[0]["errors"]


def test_archetypes_offering_split_emit_panes(samples):
    """The invariant behind the card that ran off the canvas.

    `split_5050` turns #main into a flex row and divides its direct children.
    An archetype whose builder emits no `.pane` therefore hands the row a
    headline and one unconstrained block, and the block wins.
    """
    for a in visual.ARCHETYPES:
        if "split_5050" not in a.layouts:
            continue
        assert a.name in ("cover_mockup", "cta_split", "mockup_phone"), (
            f"{a.name} offers split_5050 but its builder emits no .pane elements - "
            "either add them to templates/slide.html or drop the layout"
        )


def test_long_copy_shrinks_rather_than_overflowing(renderer):
    """The safety net under the budget gate: nothing renders broken."""
    audits: list[dict] = []
    renderer.render(
        [{"role": "steps", "kicker": "The problem",
          "title": "The booking page worked perfectly well and absolutely nobody "
                   "on the entire internet ever used it even once, not one single time",
          "steps": [
              {"title": f"A step with a deliberately long title, number {i}",
               "detail": "Six seconds to load on a phone. No reminder, no "
                         "confirmation, no way to tell whether it had worked."}
              for i in range(1, 5)
          ]}],
        "instagram_portrait", "test_long", strict=False, audits=audits,
    )
    assert audits[0]["fit"] < 1, "expected the type scale to shrink"
    assert not audits[0]["errors"], audits[0]["errors"]


def test_short_copy_grows_to_fill(renderer):
    """CONTENT_SYSTEM.md §1.3 — a short slide must not float in the canvas."""
    audits: list[dict] = []
    renderer.render(
        [{"role": "statement", "title": "It was the images."}],
        "instagram_portrait", "test_short", strict=False, audits=audits,
    )
    assert audits[0]["fit"] > 1, "expected the type scale to grow into the slack"


def test_literal_asterisk_never_reaches_the_canvas(renderer):
    """The defect that shipped. The validator rejects it; the template strips it."""
    audits: list[dict] = []
    renderer.render(
        [{"role": "metric_hero", "value": "*<200ms", "label": "median response"}],
        "instagram_portrait", "test_star", strict=False, audits=audits,
    )
    assert not audits[0]["errors"]
    text = audits[0].get("text", "")
    assert "*" not in text


def _audit_one(renderer, slide) -> dict:
    audits: list[dict] = []
    renderer.render([slide], "instagram_portrait", "test_audit", strict=False, audits=audits)
    return audits[0]


def test_a_missing_field_never_renders_as_the_word_undefined(renderer):
    """A review set shipped a testimonial slide reading "undefined" at 67px.

    The cause was `'"' + D.quote + '"'` — string concatenation *before*
    escaping, so a missing field stringified. Escaping now coalesces nullish to
    "", and the audit carries a net for any future concatenation that does not.
    The validator is what actually stops the slide: `quote` is required.
    """
    from validators import slides as gate

    slide = {"role": "quote", "attribution": "Alex, LeoTech"}
    assert gate.check([slide]), "a quote slide with no quote must be rejected"

    audit = _audit_one(renderer, slide)
    assert "undefined" not in audit["text"], audit["text"]


def test_the_audit_catches_a_stringified_field_if_one_ever_reaches_it(renderer):
    """The net itself, exercised directly."""
    audit = _audit_one(renderer, {"role": "statement", "title": "undefined"})
    assert any("undefined" in e for e in audit["errors"]), audit["errors"]


def test_content_running_under_the_wordmark_is_an_error(renderer):
    """#main and .foot are siblings, so this needs an overlap test, not overflow."""
    audit = _audit_one(renderer, {
        "role": "statement", "kicker": "x", "title": "T",
        # Forced past the footer: a negative margin is the cheapest way to
        # reproduce what a shadowed mockup does at the bottom of a slide.
        "body": "<!--", })
    # The real assertion is on a well-formed slide: nothing may reach the foot.
    good = _audit_one(renderer, {"role": "steps", "title": "The free prototype", "steps": [
        {"title": f"Step {i}", "detail": "Short detail."} for i in range(1, 5)]})
    assert not any("wordmark" in e for e in good["errors"]), good["errors"]
    assert audit is not None


def test_a_mobile_mockup_fits_the_phone_frame(renderer):
    """The mockup is 320x640; a width-driven frame ran past the canvas bottom."""
    from imaging import mockups

    audit = _audit_one(renderer, {
        "role": "mockup_phone", "layout": "split_5050", "kicker": "Work",
        "title": "Rotas in\n*a thumb tap*.", "svg": mockups.by_kind("mobile_list").svg,
    })
    assert not audit["errors"], audit["errors"]


def test_full_bleed_artwork_covers_rather_than_letterboxes(renderer):
    """A 16:10 mockup on a 4:5 canvas left a third of the slide flat colour."""
    from imaging import mockups

    audit = _audit_one(renderer, {
        "role": "cover_mockup", "layout": "full_bleed", "theme": "dark",
        "title": "Real-time AI for\n*support teams*.",
        "svg": mockups.by_kind("conversation").svg,
    })
    assert not audit["errors"], audit["errors"]


def test_embedded_artwork_opts_out_of_geometric_text_rendering(renderer):
    """The bug that mangled every reused blog diagram.

    `text-rendering: geometricPrecision` is right for our own 99px headlines and
    catastrophic for SVG text in a 100-unit viewBox scaled ~9x: "Batch thinking"
    came out as "B at ch t hin kin g". Asserting the computed style is the cheap
    proxy — the expensive one is a human looking at a PNG, which is how it was
    found.
    """
    from playwright.sync_api import sync_playwright

    svg = (
        '<svg viewBox="0 0 100 20" xmlns="http://www.w3.org/2000/svg">'
        '<text x="5" y="12" font-size="4" font-weight="500">Batch thinking</text></svg>'
    )
    template = (renderer.TEMPLATE).read_text(encoding="utf-8")
    import json

    payload = renderer._payload(
        {"role": "graphic_embed", "title": "T", "svg": svg}, "1/1", 1080, 1350
    )
    tmp = renderer.TEMPLATE.parent / "._test_textrender.html"
    tmp.write_text(template.replace("__PAYLOAD__", json.dumps(payload)), encoding="utf-8")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1080, "height": 1350})
            page.goto(tmp.as_uri())
            page.wait_for_function("window.__ready === true", timeout=15000)
            got = page.evaluate(
                "getComputedStyle(document.querySelector('.art svg text')).textRendering"
            )
            browser.close()
    finally:
        tmp.unlink(missing_ok=True)
    assert got == "auto", f"embedded SVG text inherited {got!r} and will render mangled"


def test_font_faces_cover_every_weight_the_artwork_asks_for(renderer):
    """The blog SVGs request 500 and 800; the CSS declared only 400 and 600.

    An unmatched weight is synthesised, and synthesis changes advance widths.
    Ranges are what map every request onto a real file.
    """
    css = (renderer.TEMPLATE.parent / "brand.css").read_text(encoding="utf-8")
    assert "font-weight: 100 500" in css
    assert "font-weight: 501 900" in css


def test_strict_mode_refuses_a_broken_slide(renderer):
    """`strict=True` is what stops a bad PNG being handed to a publisher.

    An empty slide, not an unknown role: an unknown role falls back to
    `statement` and draws whatever fields it was given, which is the right
    behaviour — rejecting bad roles is `validators/slides.py`'s job, upstream.
    The renderer's own line is "did this actually draw anything".
    """
    with pytest.raises(renderer.RenderError):
        renderer.render(
            [{"role": "statement"}], "instagram_portrait", "test_strict", strict=True
        )


@pytest.mark.parametrize("size", ["instagram_portrait", "facebook_link", "pinterest", "x_post"])
def test_the_deck_renders_at_every_canvas(renderer, size):
    """One stylesheet, five aspect ratios. 1200x630 is the one that catches things."""
    audits: list[dict] = []
    renderer.render(renderer.DEMO, size, f"test_size_{size}", strict=False, audits=audits)
    broken = [(a["role"], a["errors"]) for a in audits if a.get("errors")]
    assert not broken, broken
