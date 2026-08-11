"""The pre-render gate.

The first case is the one that shipped: a literal asterisk set at 216px on the
metric slide, in a review set a human had to spot by eye.
"""
from __future__ import annotations

import pytest

from campaign import visual
from validators import slides


def ok(slide: dict) -> list[str]:
    return slides.check([slide])


# ── markup ───────────────────────────────────────────────────────────────────
def test_rejects_the_asterisk_that_shipped():
    reasons = ok({"role": "metric_hero", "value": "*<200ms", "label": "median response"})
    assert any("unpaired" in r for r in reasons), reasons


@pytest.mark.parametrize(
    "text",
    [
        "Use `npm install` first",
        "Read [the guide](https://wizcodes.site/blog)",
        "## The problem",
        "It was _really_ slow",
        "- first point",
        "> a quote",
        "Line one<br>line two",
        "First line\\nsecond line",
        "Tom &amp; Jerry",
    ],
)
def test_rejects_markup_the_template_renders_literally(text):
    assert ok({"role": "statement", "title": text}), f"should reject: {text!r}"


@pytest.mark.parametrize(
    "text",
    [
        "Nine no-shows a week, *gone*",
        "The booking page worked. *Nobody used it.*",
        "Two lines\nauthored deliberately",
        "A price of $5,000 is fine here",     # the claims gate's job, not this one
        "50% faster, 3x cheaper",
    ],
)
def test_allows_what_the_template_can_actually_render(text):
    assert ok({"role": "statement", "title": text}) == [], text


def test_checks_nested_text_not_only_top_level():
    reasons = ok({
        "role": "steps", "title": "How it works",
        "steps": [
            {"title": "You describe it", "detail": "One call."},
            {"title": "We build it", "detail": "Run `make build` yourself."},
            {"title": "You decide", "detail": "Walk away owing nothing."},
        ],
    })
    assert any("steps[2].detail" in r for r in reasons), reasons


# ── structure ────────────────────────────────────────────────────────────────
def test_unknown_role_is_rejected_with_the_list():
    reasons = ok({"role": "hero_banner", "title": "x"})
    assert reasons and "cover_bold" in reasons[0]


def test_legacy_roles_still_resolve():
    """Decks written before the registry existed must still render."""
    for legacy in ("cover", "metric", "mockup", "cta"):
        assert visual.resolve(legacy) is not None, legacy
    assert visual.resolve("cover").name == "cover_bold"
    assert ok({"role": "cover", "title": "Nine no-shows, *gone*"}) == []


def test_missing_required_field_is_rejected():
    reasons = ok({"role": "metric_hero", "value": "200ms"})   # no label
    assert any("label" in r for r in reasons), reasons


def test_inline_svg_satisfies_the_image_requirement():
    """The pipeline attaches artwork as `svg`, not `image`.

    Checking only `image` rejected every graphic_embed in a review sweep whose
    artwork had been attached correctly — a validator failing the thing it was
    built to protect.
    """
    assert ok({"role": "graphic_embed", "svg": "<svg viewBox='0 0 1 1'></svg>"}) == []
    assert ok({"role": "graphic_embed", "image": "https://wizcodes.site/x.svg"}) == []
    assert ok({"role": "graphic_embed", "kicker": "From the blog"})   # neither


def test_stat_row_needs_exactly_three():
    two = ok({"role": "stat_row", "stats": [
        {"value": "30", "label": "projects"}, {"value": "11", "label": "countries"}]})
    assert any("exactly 3" in r for r in two), two
    three = ok({"role": "stat_row", "stats": [
        {"value": "30", "label": "projects"},
        {"value": "11", "label": "countries"},
        {"value": "100%", "label": "on time"}]})
    assert three == [], three


def test_comparison_bar_needs_exactly_two_series():
    assert ok({"role": "comparison_bar", "title": "Cost", "chart": {"series": [
        {"label": "Us", "value": 1}, {"label": "Them", "value": 4},
        {"label": "Other", "value": 2}]}})


def test_chart_values_must_be_numbers_not_strings():
    reasons = ok({"role": "bar_chart", "title": "Load time", "chart": {"series": [
        {"label": "Before", "value": "6s"},
        {"label": "After", "value": 0.2},
        {"label": "Target", "value": 1}]}})
    assert any("numeric" in r for r in reasons), reasons


def test_donut_value_must_be_a_percentage():
    assert ok({"role": "donut", "title": "Share", "chart": {"value": 140, "label": "of apps"}})
    assert ok({"role": "donut", "title": "Share", "chart": {"value": 78, "label": "of apps"}}) == []


def test_layout_must_compose_with_the_archetype():
    """`quote` has no artwork, so full_bleed would render an empty frame."""
    assert ok({"role": "quote", "quote": "They shipped it.", "attribution": "Priya",
               "layout": "full_bleed"})
    assert ok({"role": "quote", "quote": "They shipped it.", "attribution": "Priya",
               "layout": "centred"}) == []


# ── fit ──────────────────────────────────────────────────────────────────────
def test_metric_value_that_would_wrap_is_rejected():
    """CONTENT_SYSTEM.md §1.2 — the metric wraps and the slide loses its point."""
    reasons = ok({"role": "metric_hero", "value": "1,240 hours saved", "label": "per year"})
    assert any("budget" in r for r in reasons), reasons


def test_cover_titles_get_the_tighter_h1_budget():
    long_title = "A dental clinic in Leeds was losing nine appointments every single week"
    assert ok({"role": "cover_bold", "title": long_title})
    assert ok({"role": "statement", "title": long_title}) == []


def test_every_archetype_has_a_renderable_spec():
    """Guards the registry itself: a row with no builder is a slide that cannot draw."""
    for a in visual.ARCHETYPES:
        assert a.family in visual.FAMILIES, a.name
        assert a.layouts, a.name
        assert set(a.layouts) <= set(visual.LAYOUTS), a.name
        assert set(a.themes) <= set(visual.THEMES), a.name
        assert a.brief, a.name
        if a.imaged:
            assert a.fallback and a.fallback in visual.BY_NAME, a.name


# ── chart numbers reach the grounding gate ───────────────────────────────────
def test_chart_numbers_are_extracted_for_grounding():
    numbers = slides.chart_numbers([
        {"role": "bar_chart", "title": "t", "chart": {"unit": "%", "series": [
            {"label": "Before", "value": 47}, {"label": "After", "value": 12}]}},
        {"role": "donut", "title": "t", "chart": {"value": 78, "label": "of apps"}},
        {"role": "statement", "title": "not a chart"},
    ])
    assert numbers == ["47%", "12%", "78%"]
