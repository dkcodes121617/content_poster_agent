"""The v2 design engine's rules, in code: planner, prompt and parser.

No browser and no network here - the renderer is exercised by the design lab
on Modal (`modal run modal_app.py::lab_cli --round all`). These pin the parts
that decide what gets drawn: which formats a deck uses, how it rotates, and
what the parser refuses before anything reaches Chromium.
"""
from __future__ import annotations

import collections
import itertools
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
        assert not any(a == b and a not in select.SERIES for a, b in itertools.pairwise(f)), p.brief()
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
    assert all(a != b for a, b in itertools.pairwise(looks)), "same look twice in a row"
    assert len(set(looks)) >= 9
    assert len({p.recipe for p in plans}) >= 9
    arts = [p.art for p in plans]
    assert all(not (a == b != "none") for a, b in itertools.pairwise(arts)), "same art twice in a row"


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
    assert "max 63 characters" in spec                 # the hook's 70, stated a little under (see _shown)
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
    name: str = "AI WhatsApp Automation"
    category: str = "AI Automation"
    tech: list = field(default_factory=lambda: ["Python", "WhatsApp API", "LLM"])


@dataclass
class _Person:
    name: str
    text: str = "If we cannot show you a working prototype first, we have not earned the contract."
    role: str = ""
    company: str = "Northgate"
    country: str = "United Kingdom"
    platform: str = ""


@dataclass
class _Snapshot:
    projects: list = field(default_factory=lambda: [_Project("ai-whatsapp-automation")])
    testimonials: list = field(default_factory=lambda: [_Person("WizCodes Client")])


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


def test_quote_must_be_the_persons_own_words_and_role():
    snap = _Snapshot(testimonials=[_Person("Alex", text="Excellent communication, clean code, and timely delivery.", company="LeoTech")])
    plan = _plan(("hook", "quote", "cta"))
    real = {"quote": "Excellent communication, clean code, and timely delivery.", "name": "Alex", "role": "LeoTech"}
    _, p = prompt.parse(_raw(plan, {1: real}), plan, snap)
    assert not [x for x in p if "slide 2" in x]
    # "Alex, LeoTech" in the name field is still Alex
    _, p = prompt.parse(_raw(plan, {1: dict(real, name="Alex, LeoTech", role="")}), plan, snap)
    assert not [x for x in p if "slide 2" in x]
    # a project he is not connected to
    _, p = prompt.parse(_raw(plan, {1: dict(real, role="CuePilot Client")}), plan, snap)
    assert any("role" in x for x in p)
    # words he never wrote
    _, p = prompt.parse(_raw(plan, {1: dict(real, quote="They doubled our revenue in a month.")}), plan, snap)
    assert any("own words" in x for x in p)


def test_code_is_verbatim():
    plan = _plan(("hook", "code", "cta"))
    code = dict(GOOD["code"], code="# keys come from the environment\ndef f(*args, **kwargs):\n    return a * b")
    _, p = prompt.parse(_raw(plan, {1: code}), plan)
    assert not [x for x in p if "slide 2" in x], p


def test_budgets_shrink_on_shorter_canvases_but_labels_do_not():
    take = {"take": "x" * 70}
    assert validate("hot_take", take) == []
    assert validate("hot_take", take, canvas="square")            # 70 > 63 on a square canvas
    eyebrow = dict(GOOD["hook"], eyebrow="e" * 32)
    assert validate("hook", eyebrow, canvas="square") == []       # one-line labels keep their budget


def test_vs_validation_follows_the_layout():
    cols = {"left": {"label": "A", "points": ["one", "two"]}, "right": {"label": "B", "points": ["one", "two"]}}
    assert validate("vs", cols, "columns") == []
    assert any("TABLE" in x for x in validate("vs", cols, "table"))
    table = {"left": {"label": "A"}, "right": {"label": "B"},
             "rows": [{"aspect": "x", "left": "a", "right": "b"}] * 3}
    assert validate("vs", table, "table") == []
    assert any("COLUMNS" in x for x in validate("vs", table, "columns"))


class _FakeClient:
    """Plays back responses; records what it was asked."""

    def __init__(self, responses):
        self.responses, self.prompts = list(responses), []

    def complete(self, *, system, user, max_tokens=0, temperature=None):
        self.prompts.append(user)
        return self.responses.pop(0)


def test_write_repairs_only_the_failing_slide():
    plan = _plan()
    over = dict(GOOD["cheat_sheet"], title="x" * 90)
    fixed = {"slides": [{"index": 2, "content": GOOD["cheat_sheet"]}]}
    client = _FakeClient([_raw(plan, {1: over}), json.dumps(fixed)])
    draft, problems, attempts = prompt.write(client, system="s", user="u", plan=plan)
    assert problems == [] and [a["mode"] for a in attempts] == ["draft", "repair"]
    assert "YOUR DRAFT WAS CHECKED" in client.prompts[1] and "slide 2" in client.prompts[1]
    assert draft["slides"][1]["content"]["title"] == GOOD["cheat_sheet"]["title"]
    assert draft["slides"][0]["content"] == GOOD["hook"]          # untouched slides are kept


def test_write_regenerates_when_the_draft_cannot_be_read():
    plan = _plan()
    client = _FakeClient(["not json at all", _raw(plan)])
    _draft, problems, attempts = prompt.write(client, system="s", user="u", plan=plan)
    assert problems == [] and [a["mode"] for a in attempts] == ["draft", "draft"]


def test_gates_say_where_each_problem_is(snapshot):
    from design import gates

    plan = _plan(("hook", "steps", "cta"))
    steps = {"title": "How it runs", "steps": [{"head": "Week 1: we build the core flow"}, {"head": "Week 2: you test it"},
                                               {"head": "Week 3: you decide"}]}
    draft, _ = prompt.parse(_raw(plan, {1: steps}), plan)
    problems = gates.check(draft, platform_name="instagram", snapshot=snapshot, image_count=3)
    assert any(x.startswith("slide 2: [claims]") for x in problems), problems


def test_phone_mockups_take_the_app_from_the_facts():
    plan = _plan(("hook", "mockup", "cta"))
    plan.slides[1] = select.SlidePlan("mockup", "phone", "bg")
    content = {"title": "A WhatsApp assistant", "project": "ai-whatsapp-automation"}
    draft, _ = prompt.parse(_raw(plan, {1: content}), plan, _Snapshot())
    app = draft["slides"][1]["content"]["app"]
    assert app["name"] == "AI WhatsApp Automation" and app["initials"] == "AW" and app["tech"][0] == "Python"


class _StatSnapshot:
    projects: list = []
    testimonials: list = []

    def chartable_stats(self):
        return [{"value": 26, "label": "projects delivered", "scope": "ours"},
                {"value": 5, "label": "open-source tools published", "scope": "ours"}]

    def known_numbers(self):
        return set()


def test_a_figure_of_ours_cannot_carry_an_invented_claim():
    snap, plan = _StatSnapshot(), _plan(("hook", "stat", "recap", "cta"))
    bad_label = {"value": "26", "label": "projects delivered with fixed-scope quotes", "source": "wizcodes.site"}
    _, p = prompt.parse(_raw(plan, {1: bad_label}), plan, snap)
    assert any("set the label of 26 to exactly 'projects delivered'" in x and "fixed" in x for x in p), p
    ok = {"value": "26", "label": "projects delivered", "source": "wizcodes.site"}
    recap = dict(GOOD["recap"], note="26 projects delivered this way")
    _, p = prompt.parse(_raw(plan, {1: ok, 2: recap}), plan, snap)
    assert any(x.startswith("slide 3") and "this way" in x for x in p), p
    assert not [x for x in p if x.startswith("slide 2")]
    # a different "5" is not our five open-source tools
    hook = dict(GOOD["hook"], hook="5 questions every quote should answer")
    _, p = prompt.parse(_raw(plan, {0: hook, 1: ok}), plan, snap)
    assert not [x for x in p if x.startswith("slide 1")], p


def test_captions_are_checked_for_figure_claims_too():
    snap, plan = _StatSnapshot(), _plan(("hook", "cta"))
    raw = json.loads(_raw(plan))
    raw["caption"] = "26 projects delivered, all started with a free prototype."
    _, p = prompt.parse(json.dumps(raw), plan, snap)
    assert any(x.startswith("caption") for x in p), p


def test_charts_plot_only_real_figures():
    snap, plan = _StatSnapshot(), _plan(("hook", "chart", "cta"))
    fake = dict(GOOD["chart"], series=[{"label": "Price only", "value": 1}, {"label": "Scope", "value": 4}])
    _, p = prompt.parse(_raw(plan, {1: fake}), plan, snap)
    assert any("does not contain" in x or "do not contain" in x for x in p), p
    real = dict(GOOD["chart"], series=[{"label": "Projects", "value": 26}, {"label": "Tools", "value": 5}], highlight="Projects")
    _, p = prompt.parse(_raw(plan, {1: real}), plan, snap)
    assert not [x for x in p if x.startswith("slide 2")], p


def test_a_bento_stat_needs_tiles():
    assert any("BENTO" in x for x in validate("stat", {"value": "3", "label": "x", "source": "y"}, "bento"))


def test_crowded_quadrant_points_are_rejected():
    pts = [{"label": "A", "x": 0.8, "y": 0.8}, {"label": "B", "x": 0.85, "y": 0.75}]
    content = dict(GOOD["quadrant"], points=pts)
    assert any("on top of each other" in x for x in validate("quadrant", content))


def test_donuts_are_never_picked_automatically():
    for p in _simulate("instagram", 8, days=40, has_stats=True, has_project=True):
        assert not any(s.format == "chart" and s.layout == "donut" for s in p.slides)


def test_quadrant_positions_written_as_percent_are_rescaled():
    plan = _plan(("hook", "quadrant", "cta"))
    pts = [{"label": "Retainer agencies", "x": 15, "y": 85}, {"label": "WizCodes", "x": 90, "y": 25, "us": True}]
    draft, p = prompt.parse(_raw(plan, {1: dict(GOOD["quadrant"], points=pts)}), plan)
    got = draft["slides"][1]["content"]["points"]
    assert got[0]["x"] == 0.15 and got[1]["y"] == 0.25
    assert not [x for x in p if x.startswith("slide 2")], p
    off_scale = [{"label": "A", "x": 1.5, "y": 0.2}, {"label": "B", "x": 0.1, "y": 0.9}]
    assert any("0 to 1" in x for x in validate("quadrant", dict(GOOD["quadrant"], points=off_scale)))
