"""Recipes, rotation, phasing, geography and capacity.

Everything here runs with no database. `pick()` is passed an explicit `history`
list, which is the same shape `recent()` returns from Postgres — so the rotation
rules are tested against the real decision function rather than a reimplementation
of it, without needing Neon awake.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from campaign import capacity, deck, phase, recipes, regions, visual
from config import CONFIG


@pytest.fixture
def config():
    return replace(CONFIG, dry_run=True, database_url="", geo_targeting=True)


def hist(*names: str, opener: str = "cover_bold") -> list[dict]:
    now = datetime.now().astimezone()
    return [
        {"recipe": n, "archetypes": [opener, "statement"], "layouts": ["centred"],
         "theme": "light", "posted_at": now - timedelta(days=i)}
        for i, n in enumerate(names)
    ]


# ── recipes ──────────────────────────────────────────────────────────────────
def test_every_recipe_is_made_of_real_archetypes():
    for r in recipes.RECIPES:
        for name in r.shape:
            assert visual.resolve(name), f"{r.name} uses unknown archetype {name!r}"
        assert visual.resolve(r.shape[0]).family == "opener", f"{r.name} opens on a non-opener"
        assert visual.resolve(r.shape[-1]).family == "closer", f"{r.name} closes on a non-closer"


def test_every_pillar_has_at_least_one_recipe():
    for pillar in recipes.ALL_PILLARS:
        assert recipes.eligible(pillar), pillar


def test_chart_recipes_are_withheld_without_stats():
    """A chart recipe with no curated figures would invent its own numbers."""
    with_stats = {r.name for r in recipes.eligible("teach", has_stats=True, has_art=True)}
    without = {r.name for r in recipes.eligible("teach", has_stats=False, has_art=True)}
    assert "data_story" in with_stats
    assert "data_story" not in without


def test_only_diagram_recipes_are_withheld_without_artwork():
    """Mockups are generated, so a missing site graphic no longer blocks a deck.

    Before, `proof_narrative` and `teardown` needed a card in the site manifest
    and 7 of 26 projects have none. `visual_first` still needs real blog
    diagrams — that archetype exists to reuse a diagram we actually drew.
    """
    without = {r.name for r in recipes.eligible("proof", has_stats=True, has_art=False)}
    assert "visual_first" not in without
    assert "proof_narrative" in without
    assert "teardown" in without


@pytest.mark.parametrize("slides", [3, 4, 5, 6, 8, 10])
def test_fit_to_length_keeps_the_opener_and_the_closer(slides):
    recipe = recipes.BY_NAME["explainer"]
    shape = recipes.fit_to_length(recipe, slides)
    assert len(shape) == slides
    assert shape[0] == recipe.shape[0]
    assert shape[-1] == recipe.shape[-1]


def test_themes_open_and_close_dark():
    shape = ["cover_bold", "statement", "metric_hero", "cta_pill"]
    themes = recipes.apply_themes(shape, "light")
    assert themes[0] == "dark" and themes[-1] == "dark"
    assert themes[1] == "light"


# ── the rotation rules (§3.4) ────────────────────────────────────────────────
def test_never_the_same_recipe_twice_in_a_fortnight(config):
    used = hist("explainer", "myth_buster", "straight_talk")
    picked, _, _, _ = recipes.pick(
        config, platform="instagram", pillar="teach", slides=5,
        has_stats=True, has_art=True, today=date(2026, 8, 10), history=used,
    )
    assert picked.name not in {"explainer", "myth_buster", "straight_talk"}


def test_never_the_same_opener_twice_in_a_row(config):
    used = hist("straight_talk", opener="cover_question")
    _, archetypes, _, _ = recipes.pick(
        config, platform="threads", pillar="teach", slides=5,
        has_stats=True, has_art=True, today=date(2026, 8, 10), history=used,
    )
    assert archetypes[0] != "cover_question"


def test_a_used_up_fortnight_still_returns_a_deck(config):
    """Refusing to publish over a bookkeeping preference would be the wrong trade."""
    used = hist(*[r.name for r in recipes.RECIPES])
    picked, archetypes, layouts, theme = recipes.pick(
        config, platform="instagram", pillar="teach", slides=5,
        has_stats=True, has_art=True, today=date(2026, 8, 10), history=used,
    )
    assert picked and len(archetypes) == 5 and len(layouts) == 5 and theme


def test_the_same_slot_on_the_same_day_resolves_identically(config):
    """A retry must not re-roll the deck under an idempotency key that says done."""
    args = dict(platform="instagram", pillar="proof", slides=6,
                has_stats=True, has_art=True, today=date(2026, 8, 10), history=[])
    first = recipes.pick(config, **args)
    second = recipes.pick(config, **args)
    assert first[0].name == second[0].name
    assert first[1] == second[1] and first[2] == second[2]


def test_it_actually_varies_across_a_fortnight(config):
    """The point of the whole exercise. Simulates the ledger day by day."""
    history: list[dict] = []
    seen = []
    for day in range(14):
        picked, archetypes, _, _ = recipes.pick(
            config, platform="instagram", pillar="teach", slides=5,
            has_stats=True, has_art=True,
            today=date(2026, 8, 1) + timedelta(days=day), history=history,
        )
        seen.append(picked.name)
        history.insert(0, {
            "recipe": picked.name, "archetypes": archetypes,
            "layouts": [], "theme": "light",
            "posted_at": datetime.now().astimezone() - timedelta(days=0),
        })
    assert len(set(seen)) >= recipes.MIN_DISTINCT_PER_FORTNIGHT, seen


def test_layouts_always_compose_with_their_archetype(config):
    """The picker chooses layouts at random; the registry is what makes it safe."""
    for day in range(30):
        _, archetypes, layouts, _ = recipes.pick(
            config, platform="linkedin", pillar="proof", slides=6,
            has_stats=True, has_art=True,
            today=date(2026, 8, 1) + timedelta(days=day), history=[],
        )
        for role, layout in zip(archetypes, layouts, strict=True):
            assert layout in visual.layouts_for(role), f"{role} cannot do {layout}"


# ── phasing: the launch plan ─────────────────────────────────────────────────
def test_no_start_date_means_steady_state():
    assert phase.current(None).name == "full"


@pytest.mark.parametrize(
    ("week", "expected"),
    [(1, "launch"), (2, "launch"), (3, "compound"), (4, "compound"),
     (6, "compound"), (7, "full"), (20, "full")],
)
def test_phase_advances_by_week(week, expected):
    start = date(2026, 1, 1)
    today = start + timedelta(days=7 * (week - 1))
    assert phase.current(start, today).name == expected


def test_the_launch_withholds_only_the_selling_post():
    """Revised 9 Aug 2026. The earlier design withheld a third of every week.

    Credibility already exists on the website - 26 projects, 13 testimonials -
    so a feed that declines to use it is not building trust, it is refusing to
    spend trust it has. Only `direct_offer` waits, and only because a sales post
    needs a feed to sit in.
    """
    p = phase.current(date(2026, 1, 1), date(2026, 1, 5))
    assert p.name == "launch"
    assert not p.allows("direct_offer")
    for pillar in ("proof", "teach", "pov", "process", "client_voice"):
        assert p.allows(pillar), pillar


def test_timely_runs_from_day_one():
    """The single best discovery mechanism a new account has.

    A timely post rides a conversation already happening instead of trying to
    start one. Deferring it six weeks meant deferring the only content type that
    reaches people who have never heard of us.
    """
    assert phase.current(date(2026, 1, 1), date(2026, 1, 2)).allows("timely")


def test_the_offer_arrives_in_week_three():
    start = date(2026, 1, 1)
    assert not phase.allows("direct_offer", start, start + timedelta(days=7))
    assert phase.allows("direct_offer", start, start + timedelta(days=14))


def test_a_withheld_pillar_is_substituted_not_skipped():
    """Going quiet teaches an audience nothing worth learning."""
    start, today = date(2026, 1, 1), date(2026, 1, 5)
    assert phase.substitute("direct_offer", start, today) == "proof"
    assert phase.substitute("pov", start, today) == "pov"


def test_substitution_is_deterministic():
    start, today = date(2026, 1, 1), date(2026, 1, 5)
    assert (phase.substitute("direct_offer", start, today)
            == phase.substitute("direct_offer", start, today))


def test_every_phase_mix_sums_to_one():
    for p in phase.PHASES:
        assert abs(sum(p.mix.values()) - 1.0) < 1e-9, p.name


def test_search_intent_pillars_lead_the_launch():
    """proof + teach carry the phrases buyers type when choosing a supplier."""
    p = phase.LAUNCH
    assert p.mix["proof"] + p.mix["teach"] > 0.5


# ── geography (§4) ───────────────────────────────────────────────────────────
def test_the_posting_hour_decides_the_region():
    """13:00 IST is UK morning whatever the day rotation prefers."""
    assert regions.for_slot("threads", 13, date(2026, 8, 10)).code in ("GB", "EU")
    assert regions.for_slot("linkedin", 20, date(2026, 8, 10)).code == "US"


def test_regions_have_distinct_query_banks_not_translations():
    banks = [set(r.queries) for r in regions.REGIONS]
    for i, a in enumerate(banks):
        for b in banks[i + 1:]:
            assert not a & b, "regional queries must be written, not shared"


def test_spelling_follows_the_region():
    assert "optimize" in regions.US.spelling_note
    assert "optimise" in regions.UK.spelling_note
    assert regions.EU.locale == "en-GB"


def test_hashtags_rotate_across_days():
    seen = {
        tuple(regions.hashtags_for(regions.UK, "instagram", "proof", 3,
                                   date(2026, 8, 1) + timedelta(days=d)))
        for d in range(10)
    }
    assert len(seen) > 1, "a fixed tag set on every post is a pattern, not a bank"


def test_hashtag_count_is_respected():
    assert regions.hashtags_for(regions.US, "x", "teach", 0) == []
    assert len(regions.hashtags_for(regions.US, "x", "teach", 3)) == 3


def test_a_short_bank_is_topped_up_rather_than_returning_fewer():
    """Instagram needs 8. A five-tag bank silently returned five and was rejected."""
    tags = regions.hashtags_for(regions.UK, "instagram", "teach", 12)
    assert len(tags) == 12
    assert len(set(tags)) == 12, "no duplicates"


@pytest.mark.parametrize(
    ("platform", "produced"),
    [(p, n) for p in ("instagram", "linkedin", "threads", "facebook", "x", "pinterest")
     for n in (0, 3, 5, 20)],
)
def test_regional_hashtags_always_satisfy_the_platform_gate(config, platform, produced):
    """The interaction that broke a whole sweep: geography vs the platform gate.

    Neither side looked wrong on its own. The regional bank returned what it
    had; the platform gate wanted what it needs; nothing reconciled them.
    """
    from validators.platform import check as platform_check

    plan = deck.DeckPlan(platform=platform, pillar="teach", recipe="x", region=regions.UK)
    tags = deck.hashtags(config, plan, produced)
    reasons = [r for r in platform_check(platform, "A caption.", tags, 1) if "hashtag" in r]
    assert not reasons, reasons


# ── capacity + backfill (§5) ─────────────────────────────────────────────────
def test_a_ramp_never_exceeds_the_ceiling():
    for platform, plan in capacity.DEFAULTS.items():
        for _, target in capacity.ramp_schedule(platform, date(2026, 8, 1), weeks=12):
            assert target <= plan.ceiling, platform


def test_a_ramp_starts_at_the_launch_rate_and_climbs():
    rows = capacity.ramp_schedule("linkedin", date(2026, 8, 1), weeks=12)
    targets = [t for _, t in rows]
    assert targets[0] == capacity.DEFAULTS["linkedin"].launch
    assert targets == sorted(targets)
    assert targets[-1] <= capacity.DEFAULTS["linkedin"].steady


def test_a_flat_ramp_collapses_to_one_row():
    """GBP has no step-up. Twelve identical rows would say nothing."""
    assert len(capacity.ramp_schedule("gbp", date(2026, 8, 1), weeks=12)) == 1


def test_linkedin_cannot_be_ramped_to_five_a_day():
    """§5's argument, as an assertion: early reach penalties are sticky."""
    assert capacity.DEFAULTS["linkedin"].ceiling <= 2.0
    assert capacity.DEFAULTS["instagram"].ceiling <= 1.0


# ── the deck planner ─────────────────────────────────────────────────────────
def test_plan_produces_matching_length_lists(config, snapshot):
    plan = deck.plan(config, platform="instagram", pillar="proof", slides=6,
                     hour_ist=11, snapshot=snapshot, library=None,
                     today=date(2026, 8, 10), history=[])
    assert len(plan.archetypes) == 6
    assert len(plan.layouts) == 6
    assert len(plan.themes) == 6


def test_plan_records_a_phase_substitution(config, snapshot):
    phased = replace(config, campaign_start_date="2026-08-05")
    plan = deck.plan(phased, platform="threads", pillar="direct_offer", slides=5,
                     hour_ist=21, snapshot=snapshot, library=None,
                     today=date(2026, 8, 10), history=[])
    assert plan.substituted_from == "direct_offer"
    assert plan.pillar != "direct_offer"
    assert plan.phase_name == "launch"


def test_plan_leaves_pov_alone_during_the_launch(config, snapshot):
    """The revised plan withholds one pillar, not three."""
    phased = replace(config, campaign_start_date="2026-08-05")
    plan = deck.plan(phased, platform="threads", pillar="pov", slides=5,
                     hour_ist=21, snapshot=snapshot, library=None,
                     today=date(2026, 8, 10), history=[])
    assert plan.substituted_from == ""
    assert plan.pillar == "pov"


def test_a_mockup_slide_always_gets_artwork(config, snapshot):
    """There is no longer such a thing as a project we cannot picture.

    This used to downgrade to `cover_bold` whenever the site had no card, which
    is also what made the artwork mismatch possible: the lookup that could fail
    was the lookup that could pick the wrong project.
    """
    plan = deck.DeckPlan(
        platform="instagram", pillar="proof", recipe="proof_narrative",
        archetypes=["cover_mockup"], layouts=["split_5050"], themes=["dark"],
    )
    out = deck.decorate([{"title": "Shift planning for *three clinics*."}], plan,
                        library=None, snapshot=snapshot)
    assert out[0]["role"] == "cover_mockup"
    assert out[0]["svg"] and out[0]["_art"].startswith("mockup:")


def test_graphic_embed_still_downgrades_with_no_diagram_library(config, snapshot):
    """The one imaged archetype that can still come up empty."""
    plan = deck.DeckPlan(
        platform="instagram", pillar="teach", recipe="visual_first",
        archetypes=["graphic_embed"], layouts=["centred"], themes=["light"],
    )
    out = deck.decorate([{"title": "The four guardrails", "body": "A diagram."}], plan,
                        library=None, snapshot=snapshot)
    assert out[0]["role"] == "statement"
    assert "svg" not in out[0]


def test_decorate_never_leaves_an_impossible_layout(config, snapshot):
    plan = deck.DeckPlan(
        platform="instagram", pillar="proof", recipe="x",
        archetypes=["quote"], layouts=["full_bleed"], themes=["light"],
    )
    out = deck.decorate([{"quote": "They shipped it.", "attribution": "Priya"}], plan,
                        library=None, snapshot=snapshot)
    assert out[0]["layout"] in visual.layouts_for("quote")


def test_variety_off_reproduces_the_original_single_shape(config, snapshot):
    plain = replace(config, visual_variety=False)
    plan = deck.plan(plain, platform="instagram", pillar="proof", slides=5,
                     hour_ist=11, snapshot=snapshot, library=None,
                     today=date(2026, 8, 10), history=[])
    assert plan.recipe == recipes.FALLBACK
    assert set(plan.layouts) == {"centred"}


def test_a_planned_deck_passes_the_pre_render_gate(config, snapshot):
    """End to end through the planner: whatever it plans must be renderable."""
    from validators import slides as gate

    for day in range(10):
        plan = deck.plan(config, platform="instagram", pillar="teach", slides=6,
                         hour_ist=11, snapshot=snapshot, library=None,
                         today=date(2026, 8, 1) + timedelta(days=day), history=[])
        # Fill every required field the way a compliant writer would.
        written = [_stub(role) for role in plan.archetypes]
        decorated = deck.decorate(written, plan, library=None, snapshot=snapshot)
        assert gate.check(decorated) == [], (plan.recipe, gate.check(decorated))


def _stub(role: str) -> dict:
    """Minimal valid content for an archetype — what a compliant writer returns."""
    a = visual.resolve(role)
    slide: dict = {}
    filler = {
        "title": "It was the images", "body": "Six seconds on a phone.",
        "kicker": "The problem", "value": "200ms", "label": "median response",
        "quote": "They shipped it.", "attribution": "Priya Raman",
        "pill": "wizcodes.site", "note": "No retainer.", "caption": "A diagram.",
        "myth": "You need the full spec.", "fact": "You need one screen.",
        "image": "x", "url": "wizcodes.site/work/cuepilot",
    }
    for name in a.required + a.optional:
        if name == "steps":
            slide["steps"] = [{"title": f"Step {i}", "detail": "Short."} for i in range(1, 4)]
        elif name == "items":
            slide["items"] = ["Who owns the code", "What if they leave", "Is hosting in"]
        elif name == "nodes":
            slide["nodes"] = ["Brief", "Prototype", "Build"]
        elif name == "stats":
            slide["stats"] = [{"value": str(v), "label": "things"} for v in (26, 11, 5)]
        elif name == "before":
            slide["before"] = {"label": "Before", "text": "Six seconds."}
        elif name == "after":
            slide["after"] = {"label": "After", "text": "Under 200ms."}
        elif name == "chart":
            slide["chart"] = (
                {"value": 78, "label": "of sessions"} if role == "donut"
                else {"unit": "s", "series": [
                    {"label": f"Bar {i}", "value": float(i)}
                    for i in range(1, 3 if role == "comparison_bar" else 4)]}
            )
        elif name in filler:
            slide[name] = filler[name]
    return slide


# ── the launch boost ─────────────────────────────────────────────────────────
def test_the_boost_is_time_bounded_and_ends_on_its_own():
    """A boost somebody has to remember to switch off runs for a year."""
    from campaign.calendar import boost_active

    start = date(2026, 8, 10)
    assert boost_active(start, 3, start)
    assert boost_active(start, 3, start + timedelta(days=20))
    assert not boost_active(start, 3, start + timedelta(days=21))
    assert not boost_active(None, 3, start), "no start date means no boost"
    assert not boost_active(start, 0, start), "BOOST_WEEKS=0 disables it"


def test_boost_slots_do_not_fire_outside_the_window():
    from campaign.calendar import WEEK, due_slots

    live = ["instagram", "facebook", "threads", "pinterest", "x"]
    boost_only = [s for s in WEEK if s.boost]
    assert boost_only, "there should be boost slots"
    # Every hour of a whole week, with and without the boost.
    from zoneinfo import ZoneInfo

    ist = ZoneInfo("Asia/Kolkata")

    def week(boost):
        return sum(
            len(due_slots(datetime(2026, 8, 10 + d, h, 0, tzinfo=ist), live, boost=boost))
            for d in range(7) for h in range(24)
        )

    normal, boosted = week(False), week(True)
    assert boosted > normal, (normal, boosted)


def test_the_boost_is_weighted_to_platforms_that_tolerate_volume():
    """Pinterest is a search index; Meta feeds punish a new account's frequency.

    Instagram must not more than double, or the boost risks the account it is
    meant to fill.
    """
    from campaign.calendar import WEEK

    def per_week(platform, boost):
        return sum(1 for s in WEEK if s.platform == platform and (boost or not s.boost))

    assert per_week("pinterest", True) >= per_week("pinterest", False) * 3
    assert per_week("instagram", True) <= per_week("instagram", False) * 2
    assert per_week("facebook", True) <= per_week("facebook", False) * 2
    assert per_week("x", True) == per_week("x", False), "X is hand-published"


def test_boosted_volume_stays_under_every_ceiling():
    """§5's ceilings are the argument about spam, enforced."""
    import collections

    from campaign import capacity
    from campaign.calendar import WEEK

    counts = collections.Counter(s.platform for s in WEEK)
    for platform, n in counts.items():
        plan = capacity.DEFAULTS.get(platform)
        if not plan:
            continue
        assert n / 7 <= plan.ceiling, f"{platform}: {n}/week exceeds {plan.ceiling}/day"


def test_pinterest_gets_a_looser_repetition_rule():
    """Several pins on one subject aimed at different phrases is how it works."""
    from validators import repetition_threshold_for

    assert repetition_threshold_for("pinterest", 0.86) > 0.86
    assert repetition_threshold_for("threads", 0.86) == 0.86
    # A per-platform value may loosen, never tighten silently.
    assert repetition_threshold_for("pinterest", 0.97) == 0.97
