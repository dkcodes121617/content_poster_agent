"""The v2 design engine's rules, in code: planner, prompt and parser.

No browser and no network here - the renderer is exercised by the design lab
on Modal (`modal run modal_app.py::lab_cli --round all`). These pin the parts
that decide what gets drawn: which formats a deck uses, how it rotates, and
what the parser refuses before anything reaches Chromium.
"""
from __future__ import annotations

import collections
import json
from dataclasses import dataclass, field
from datetime import date, timedelta

import pytest

from design import prompt, select
from design.fixtures import GOOD, hostile
from design.registry import FORMATS, LOOKS, validate

PILLARS = ("teach", "pov", "proof", "process", "timely", "client_voice", "direct_offer")


# ── registry ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("fid", sorted(FORMATS))
def test_good_fixture_validates(fid):
    assert validate(fid, GOOD[fid]) == []


@pytest.mark.parametrize("fid", sorted(FORMATS))
def test_hostile_fixture_is_at_the_limit_and_still_valid(fid):
    # Hostile copy fills every field to its budget; the lab renders it in
    # every look. It must be valid, or the lab would be testing nothing.
    assert validate(fid, hostile(fid)) == []


def test_over_budget_is_rejected_with_a_usable_reason():
    bad = dict(GOOD["hook"], hook="x" * 200)
    problems = validate("hook", bad)
    assert problems and "max 70" in problems[0]


def test_emphasis_marks_do_not_count_against_budgets():
    ok = dict(GOOD["hook"], hook="*" + "a" * 70 + "*")
    assert validate("hook", ok) == []


# ── planner ──────────────────────────────────────────────────────────────────


def _simulate(platform, slides, days=21, **kw):
    history, plans = [], []
    for d in range(days):
        p = select.plan(platform=platform, pillar=PILLARS[d % len(PILLARS)], slides=slides, history=history,
                        today=date(2026, 10, 5) + timedelta(days=d), slot_key=f"{platform}-{d}", **kw)
        history = [{"recipe": p.recipe, "design": p.to_record()}, *history]
        plans.append(p)
    return plans


def test_plan_is_deterministic():
    kw = dict(platform="linkedin", pillar="teach", slides=8, history=[], today=date(2026, 10, 6), slot_key="a")
    assert select.plan(**kw).to_record() == select.plan(**kw).to_record()


@pytest.mark.parametrize("platform", ["threads", "x", "youtube", "devto"])
def test_text_first_platforms_get_no_design(platform):
    assert select.plan(platform=platform, pillar="pov", slides=1) is None


@pytest.mark.parametrize("slides", [3, 4, 5, 6, 7, 8, 9, 10])
@pytest.mark.parametrize("platform", ["linkedin", "instagram"])
def test_deck_structure(platform, slides):
    for p in _simulate(platform, slides, has_stats=True, has_project=True):
        f = p.formats
        assert f[0] == "hook" and f[-1] == "cta", p.brief()
        assert min(slides, 7) <= len(f) <= slides, p.brief()
        body = collections.Counter(f[1:-1])
        assert all(v <= select.REPEAT_LIMIT.get(k, 1) for k, v in body.items()), p.brief()
        assert not any(a == b and a not in select.SERIES for a, b in zip(f, f[1:], strict=False)), p.brief()
        for s in p.slides:
            assert s.layout in FORMATS[s.format].layouts


def test_repeated_formats_change_layout_inside_a_deck():
    for p in _simulate("linkedin", 9, has_stats=True, has_project=True):
        for fid in set(p.formats):
            lays = [s.layout for s in p.slides if s.format == fid]
            if len(lays) > 1 and len(FORMATS[fid].layouts) >= len(lays):
                assert len(set(lays)) == len(lays), p.brief()


@pytest.mark.parametrize("platform,slides", [("linkedin", 8), ("instagram", 7), ("pinterest", 1), ("facebook", 1)])
def test_rotation_varies_the_feed(platform, slides):
    plans = _simulate(platform, slides, days=30, has_stats=True, has_project=True)
    looks = [p.look for p in plans]
    assert all(a != b for a, b in zip(looks, looks[1:], strict=False)), "same look twice in a row"
    assert len(set(looks)) >= 9
    assert len({p.recipe for p in plans}) >= 9
    arts = [p.art for p in plans]
    assert all(not (a == b != "none") for a, b in zip(arts, arts[1:], strict=False)), "same art twice in a row"


def test_no_chart_without_stats_and_no_mockup_without_projects():
    for p in _simulate("instagram", 8, has_stats=False, has_project=False):
        assert "chart" not in p.formats and "mockup" not in p.formats, p.brief()
    for p in _simulate("facebook", 1, has_stats=False, has_project=False):
        assert p.formats[0] not in ("chart", "mockup")


def test_singles_never_use_carousel_only_formats():
    for p in _simulate("pinterest", 1, days=40, has_stats=True, has_project=True):
        assert FORMATS[p.formats[0]].family in ("single", "both"), p.brief()


def test_service_line_pins_the_accent():
    p = select.plan(platform="linkedin", pillar="proof", slides=6, service_line="Mobile Apps")
    assert p.accent == "teal"


def test_art_belongs_to_the_look():
    for p in _simulate("instagram", 6, has_stats=True, has_project=True):
        assert p.art == "none" or p.art in LOOKS[p.look].art


# ── prompt ───────────────────────────────────────────────────────────────────


def _plan(formats=("hook", "cheat_sheet", "chart", "cta")):
    return select.DesignPlan(platform="linkedin", pillar="teach", recipe="test", goal="saves", feels_like="x",
                             canvas="portrait", look="midnight", accent="blue", art="orbits", seed=1,
                             slides=[select.SlidePlan(f, FORMATS[f].layouts[0], "bg") for f in formats])


def _raw(plan, overrides=None):
    slides = [{"format": s.format, "content": json.loads(json.dumps(GOOD[s.format]))} for s in plan.slides]
    for i, content in (overrides or {}).items():
        slides[i]["content"] = content
    return json.dumps({"title": "T", "caption": "A caption that earns the tap.", "hashtags": ["#a", "b"], "slides": slides})


def test_spec_names_every_slide_and_its_budgets():
    plan = _plan()
    spec = prompt.deck_spec(plan)
    for i, s in enumerate(plan.slides, 1):
        assert f"Slide {i}:" in spec and f"[{s.format}]" in spec
    assert "max 70 characters" in spec                 # the hook's budget, from the registry
    assert "each object:" in spec                      # list-of-object fields are spelled out
    assert "Icon fields take one of" in spec


def test_parse_accepts_a_valid_deck():
    plan = _plan()
    draft, problems = prompt.parse(_raw(plan), plan)
    assert problems == []
    assert [s["format"] for s in draft["slides"]] == plan.formats
    assert draft["hashtags"] == ["a", "b"]


def test_parse_rejects_wrong_count_budget_markup_and_marks():
    plan = _plan()
    _, p = prompt.parse(json.dumps({"caption": "c", "slides": [{"format": "hook", "content": GOOD["hook"]}]}), plan)
    assert any("the deck has 4 slides" in x for x in p)
    over = dict(GOOD["cheat_sheet"], title="x" * 90)
    _, p = prompt.parse(_raw(plan, {1: over}), plan)
    assert any("max 54" in x for x in p)
    md = dict(GOOD["hook"], hook="**Bold** `code` here")
    _, p = prompt.parse(_raw(plan, {0: md}), plan)
    assert any("backtick" in x for x in p) or any("more than one phrase" in x for x in p)
    unclosed = dict(GOOD["hook"], hook="An *unclosed mark")
    _, p = prompt.parse(_raw(plan, {0: unclosed}), plan)
    assert any("unclosed emphasis" in x for x in p)


def test_unknown_icons_are_replaced_not_regenerated():
    plan = _plan()
    cells = json.loads(json.dumps(GOOD["cheat_sheet"]))
    cells["cells"][0]["icon"] = "definitely-not-an-icon"
    draft, problems = prompt.parse(_raw(plan, {1: cells}), plan)
    assert problems == []
    assert draft["slides"][1]["content"]["cells"][0]["icon"] == "sparkles"


@dataclass
class _Project:
    slug: str


@dataclass
class _Person:
    name: str


@dataclass
class _Snapshot:
    projects: list = field(default_factory=lambda: [_Project("ai-whatsapp-automation")])
    testimonials: list = field(default_factory=lambda: [_Person("Priya Raman")])


def test_structural_claims_are_grounded():
    plan = _plan(("hook", "mockup", "quote", "cta"))
    bad_mock = dict(GOOD["mockup"], project="invented-project")
    bad_quote = dict(GOOD["quote"], name="Somebody Invented")
    _, p = prompt.parse(_raw(plan, {1: bad_mock, 2: bad_quote}), plan, _Snapshot())
    assert any("invented-project" in x for x in p)
    assert any("Somebody Invented" in x for x in p)
    good_quote = dict(GOOD["quote"], name="WizCodes")
    _, p = prompt.parse(_raw(plan, {2: good_quote}), plan, _Snapshot())
    assert not any("testimonial" in x for x in p)


def test_visible_text_writes_chart_numbers_out_for_the_grounding_gate():
    text = prompt.visible_text([{"format": "chart", "content": GOOD["chart"]}])
    assert "Projects: 26." in text and "*" not in text
