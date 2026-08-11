"""One deliberate end-to-end run, into its own folder, for review.

    python tools/e2e.py                    everything (~20 min, ~25 proxy calls)
    python tools/e2e.py --posts 6          fewer generated posts
    python tools/e2e.py --only visual      just the archetype x layout matrix
    python tools/e2e.py --only guards      just the guardrail table (no LLM)

`tools/showcase.py` answers "does today's content look right". This answers a
different question: **does the whole system behave correctly across everything it
can do** — every recipe, every region, every campaign phase, every archetype in
every layout, and every edge case the gates exist for.

Three sections, and they need different things:

  A. **Generated posts** — the real pipeline. Real prompts, real proxy calls,
     all six validators, real Chromium. Deliberately spread so all eight recipes,
     three regions, four phases, six platforms and five formats are covered
     rather than whatever the rotation happened to pick.

  B. **Visual matrix** — every archetype in every layout it claims, rendered
     with fixed copy. No LLM: the question is whether the composition holds, and
     varying the words would make two runs incomparable.

  C. **Guardrails** — every edge case, as input → expected → actual. Almost all
     deterministic, so this section is the one that can be diffed between runs.

## Only the Claude proxy

Every LLM call goes through `wizcore.llm.client`, which is pointed at
`ANTHROPIC_BASE_URL`. Nothing here touches Groq: trend *scoring* uses it, and
this tool never runs the trend pipeline — it only reads angles the harvester
already verified. Asserted at startup rather than assumed.

## Nothing is published

`DRY_RUN` is forced on. No idempotency claim is taken, no trend angle is
consumed, and no row is written to `content.visual_history` — a review run is not
a fortnight of publishing, and recording it would make the real rotation think it
had already used eight recipes today.
"""
from __future__ import annotations

import argparse
import dataclasses
import html
import json
import shutil
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

AGENT_ROOT = Path(__file__).resolve().parent.parent
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

# The Windows console is cp1252, and this tool prints archetype sequences with
# arrows in them. A review harness must not die reporting where its report is.
for _stream in (sys.stdout, sys.stderr):
    with __import__("contextlib").suppress(AttributeError, ValueError):
        _stream.reconfigure(encoding="utf-8", errors="replace")


# ══════════════════════════════════════════════════════════════════════════════
# A. Generated posts
# ══════════════════════════════════════════════════════════════════════════════
# (platform, pillar, fmt, slides, hour, recipe, phase)
#
# `phase` is a label, not a date: the runner back-dates CAMPAIGN_START_DATE so
# that phase is genuinely in force, which is the only way to see the pillar
# substitution actually happen rather than assert it in a unit test.
#
# `recipe` empty means "let the ledger choose", which is what production does.
CASES: list[tuple[str, str, str, int, int, str, str]] = [
    # ── every recipe, once, on a platform that suits it ──
    ("instagram", "proof", "carousel", 6, 13, "proof_narrative", "full"),
    ("instagram", "teach", "carousel", 6, 13, "data_story", "full"),
    ("instagram", "teach", "carousel", 5, 12, "visual_first", "full"),
    ("linkedin", "pov", "carousel", 6, 18, "myth_buster", "full"),
    ("linkedin", "teach", "carousel", 8, 18, "teardown", "full"),
    ("facebook", "process", "single", 0, 20, "explainer", "full"),
    ("instagram", "direct_offer", "carousel", 4, 13, "offer", "full"),
    ("facebook", "proof", "single", 0, 20, "straight_talk", "full"),
    # ── every remaining platform and format ──
    ("threads", "pov", "text", 0, 21, "", "full"),
    ("threads", "teach", "text", 0, 14, "", "full"),          # UK hour -> en-GB
    ("pinterest", "proof", "pin", 0, 15, "", "full"),         # 400 chars, no tags
    ("x", "teach", "thread", 0, 19, "", "full"),              # 5-8 tweets
    ("x", "pov", "thread", 0, 14, "", "full"),
    ("facebook", "client_voice", "single", 0, 12, "", "full"),  # EU hour
    # ── the trend path. Skips cleanly when no angle is ready. ──
    ("threads", "timely", "text", 0, 21, "", "full"),
    ("linkedin", "timely", "text", 0, 18, "", "full"),
    # ── phasing: the same slots under earlier phases ──
    ("instagram", "proof", "carousel", 6, 13, "", "launch"),
    ("instagram", "direct_offer", "carousel", 4, 13, "", "launch"),  # withheld
    ("threads", "timely", "text", 0, 21, "", "launch"),       # timely runs day 1
    ("instagram", "pov", "carousel", 5, 13, "", "compound"),  # nothing withheld
]

PHASE_START = {
    "launch": 3,        # days ago
    "compound": 17,
    "full": 60,
}


def generate(config, cases, out_dir: Path) -> list[dict]:
    from wizcore.facts.site import SiteReader
    from wizcore.facts.snapshot import build_snapshot
    from wizcore.llm.client import LLMClient, extract_json

    from campaign import deck as deck_mod
    from campaign import keywords, regions
    from campaign.calendar import today_ist
    from graph.nodes import _slide_text, _timely_context
    from imaging import render as render_mod
    from imaging.graphics import GraphicsLibrary
    from prompts.library import post_system_prompt, post_user_prompt
    from validators import validate

    reader = SiteReader(
        repo=config.site_repo, token=config.site_read_token,
        ref=config.site_branch, local_dir=config.site_local_dir or None,
    )
    snapshot = build_snapshot(reader)
    facts = snapshot.to_prompt_block(include_testimonials=True)
    stats = snapshot.stats_block()
    library = GraphicsLibrary(reader) if config.site_artwork else None
    client = LLMClient(model=config.voice_model)
    today = today_ist(config.display_tz)

    results: list[dict] = []
    history: list[str] = []
    ledger: dict[str, list[dict]] = {}

    for index, (platform, pillar, fmt, slides, hour, recipe, phase_name) in enumerate(cases, 1):
        label = f"{platform}/{pillar}"
        print(f"[A {index}/{len(cases)}] {label:26} {recipe or '(ledger)':16} {phase_name}",
              flush=True)
        started = time.time()

        # Back-date the campaign so this phase is genuinely current.
        cfg = dataclasses.replace(
            config,
            campaign_start_date=(today - timedelta(days=PHASE_START[phase_name])).isoformat(),
        )
        deck = deck_mod.plan(
            cfg, platform=platform, pillar=pillar, slides=slides, hour_ist=hour,
            snapshot=snapshot, library=library, today=today,
            history=ledger.get(platform, []), recipe=recipe,
        )

        angle_row, sources, extra = (None, [], "")
        if deck.pillar == "timely":
            class _Slot:
                pass
            slot = _Slot()
            slot.pillar, slot.platform = "timely", platform
            angle_row, sources, extra = _timely_context(cfg, slot)
            if not angle_row:
                results.append({
                    "platform": platform, "pillar": pillar, "requested_pillar": pillar,
                    "fmt": fmt, "requested_recipe": recipe, "phase": phase_name,
                    "skipped": "no verified trend angle is ready right now",
                })
                continue

        attempts: list[dict] = []
        accepted = None
        note = ""
        for attempt in range(1, cfg.max_regenerations + 2):
            try:
                raw = client.complete(
                    system=post_system_prompt(facts, stats),
                    user=post_user_prompt(
                        deck.pillar, platform, fmt, slides, extra + note,
                        archetypes=deck.archetypes,
                        region_brief=regions.brief(deck.region) if cfg.geo_targeting else "",
                        phrase_brief=(
                            keywords.brief(deck.phrase, platform) if deck.phrase else ""
                        ),
                    ),
                    max_tokens=2200, temperature=0.85,
                )
            except Exception as e:
                attempts.append({"attempt": attempt, "error": str(e)[:300]})
                break

            parsed = extract_json(raw)
            if not isinstance(parsed, dict):
                attempts.append({"attempt": attempt, "reasons": ["model did not return JSON"]})
                note = "\n\nReturn only the JSON object."
                continue

            caption = str(parsed.get("caption") or "").strip()
            tags = [str(h) for h in (parsed.get("hashtags") or []) if str(h).strip()]
            slide_list = deck_mod.decorate(
                parsed.get("slides") or [], deck, library=library, snapshot=snapshot
            )
            regional = deck_mod.hashtags(cfg, deck, len(tags), today)
            if regional:
                tags = regional
            image_count = (
                len(slide_list) if fmt == "carousel"
                else 0 if platform in ("threads", "x", "youtube") else 1
            )
            verdict = validate(
                caption=caption, hashtags=tags, image_count=image_count,
                platform_name=platform, snapshot=snapshot, history=history,
                slides_text=" ".join(_slide_text(s) for s in slide_list),
                slides=slide_list, sources=sources,
                repetition_threshold=cfg.repetition_threshold,
                phrase=deck.phrase, seo_required=cfg.seo_phrase_required,
                pillar=deck.pillar,
            )
            attempts.append({
                "attempt": attempt, "chars": len(caption),
                "gates": verdict.failed_gates, "reasons": verdict.reasons,
                "passed": verdict.ok,
            })
            if verdict.ok:
                accepted = {"caption": caption, "hashtags": tags, "slides": slide_list}
                history.append(caption)
                break
            note = (
                "\n\nThe previous draft was rejected:\n"
                + "\n".join(f"- {r}" for r in verdict.reasons)
                + "\nWrite a fresh version."
            )

        record = {
            # `pillar` is the EFFECTIVE one. Recording the requested pillar here
            # made the phasing rows read "pov withheld -> pov", which is the
            # substitution the report exists to show, displayed as a no-op.
            "platform": platform, "pillar": deck.pillar, "requested_pillar": pillar,
            "fmt": fmt, "requested_recipe": recipe, "recipe": deck.recipe,
            "archetypes": deck.archetypes, "layouts": deck.layouts, "themes": deck.themes,
            "region": deck.region.code, "locale": deck.region.locale,
            "phase": deck.phase_name, "substituted_from": deck.substituted_from,
            "phrase": deck.phrase.text if deck.phrase else "",
            "phrase_tier": deck.phrase.tier if deck.phrase else "",
            "hour_ist": hour, "attempts": attempts,
            "seconds": round(time.time() - started, 1),
            "angle": (angle_row or {}).get("headline"),
            "citation": (angle_row or {}).get("citation"),
        }
        ledger.setdefault(platform, []).insert(0, {
            "recipe": deck.recipe, "archetypes": deck.archetypes,
            "layouts": deck.layouts, "theme": "", "posted_at": datetime.now().astimezone(),
        })
        if accepted:
            from campaign import keywords as _kw

            record["slug"] = _kw.slug_preview(accepted["caption"].splitlines()[0])
        if not accepted:
            record["failed"] = "no draft passed all seven validators"
            results.append(record)
            continue

        record.update(accepted)
        audits: list[dict] = []
        record["images"] = _render_into(
            render_mod.render_slides, accepted["slides"], platform,
            f"A{index:02d}_{platform}_{pillar}",
            out_dir, audits, caption=accepted["caption"], pillar=pillar,
        )
        record["audit"] = audits
        results.append(record)

    return results


def _render_into(render_fn, slides, platform, folder_name, out_dir, audits,
                 caption="", pillar="") -> list[str]:
    """Render and copy into the report folder. Never strict — see a bad slide.

    `render_fn(slides, platform, prefix, strict=, audits=)`. Section A passes
    `imaging.render.render_slides`, which maps a platform to its canvas; section
    B passes a partial over `tools/render.py`'s `render`, which takes a canvas
    name directly. Taking a callable rather than a module is what stopped the
    two being confused — the first version called `render_slides` on the module
    that does not have it, and section B rendered nothing at all.
    """
    from graph.nodes import _fallback_slide
    from platforms import Draft

    if platform in ("threads", "x", "youtube"):
        return []
    slides = slides or [_fallback_slide(Draft(platform=platform, pillar=pillar, caption=caption))]
    try:
        paths = render_fn(slides, platform, folder_name, strict=False, audits=audits)
    except Exception as e:
        print(f"    render failed: {e}")
        return []
    folder = out_dir / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    copied = []
    for path in paths:
        target = folder / Path(path).name
        shutil.copy2(path, target)
        copied.append(str(target.relative_to(out_dir)).replace("\\", "/"))
    return copied


# ══════════════════════════════════════════════════════════════════════════════
# B. Visual matrix — every archetype in every layout it claims
# ══════════════════════════════════════════════════════════════════════════════
def visual_matrix(config, out_dir: Path) -> list[dict]:
    import importlib.util

    from campaign import visual
    from imaging.graphics import PLACEHOLDER_SVG

    spec = importlib.util.spec_from_file_location("cp_render", AGENT_ROOT / "tools" / "render.py")
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)

    samples = {s["role"]: s for s in renderer.sample_slides()}
    # Themes rotate across the matrix so all three appear without tripling the
    # render count. The composition is what is under test, not the palette.
    themes = ("light", "dark", "tinted")

    slides, meta = [], []
    n = 0
    for archetype in visual.ARCHETYPES:
        base = samples.get(archetype.name)
        if not base:
            continue
        for layout in archetype.layouts:
            theme = themes[n % len(themes)]
            if theme not in archetype.themes:
                theme = archetype.themes[0]
            slide = {**base, "layout": layout, "theme": theme}
            if slide.get("svg") == "__PLACEHOLDER__":
                slide["svg"] = PLACEHOLDER_SVG
            slides.append(slide)
            meta.append({"role": archetype.name, "family": archetype.family,
                         "layout": layout, "theme": theme})
            n += 1

    print(f"[B] rendering {len(slides)} archetype x layout combinations ...", flush=True)
    audits: list[dict] = []
    def _render(sl, _platform, prefix, *, strict=False, audits=None):
        return renderer.render(sl, "instagram_portrait", prefix, strict=strict, audits=audits)

    images = _render_into(_render, slides, "instagram", "B_visual_matrix", out_dir, audits)
    for i, entry in enumerate(meta):
        entry["image"] = images[i] if i < len(images) else ""
        entry["audit"] = audits[i] if i < len(audits) else {}
    return meta


# ══════════════════════════════════════════════════════════════════════════════
# C. Guardrails — every edge case, as input -> expected -> actual
# ══════════════════════════════════════════════════════════════════════════════
def guardrails(config, snapshot, out_dir: Path) -> list[dict]:
    from wizcore.facts import grounding

    from campaign import capacity, phase, recipes, regions, visual
    from campaign import deck as deck_mod
    from campaign.calendar import today_ist
    from validators import claims, voice
    from validators import platform as platform_gate
    from validators import slides as slide_gate
    from validators.platform import LIMITS

    out: list[dict] = []

    def case(group, name, expect_block, got_reasons, detail=""):
        blocked = bool(got_reasons)
        out.append({
            "group": group, "case": name, "expected": "blocked" if expect_block else "allowed",
            "actual": "blocked" if blocked else "allowed",
            "ok": blocked == expect_block,
            "why": (got_reasons[0][:220] if got_reasons else ""), "detail": detail,
        })

    def slide(d):
        return slide_gate.check([d])

    # ── markup that the template renders literally ──
    for name, text in [
        ("backtick", "Run `npm install` first"),
        ("markdown link", "Read [the guide](https://wizcodes.site/blog)"),
        ("heading marker", "## The problem"),
        ("underscore italics", "It was _really_ slow"),
        ("bullet", "- first point"),
        ("blockquote", "> a quote"),
        ("HTML tag", "Line one<br>line two"),
        ("escaped newline", "First\\nsecond"),
        ("HTML entity", "Tom &amp; Jerry"),
        ("unpaired asterisk", "*Nine no-shows"),
    ]:
        case("Markup", name, True, slide({"role": "statement", "title": text}))
    for name, text in [
        ("paired emphasis", "Nine no-shows a week, *gone*"),
        ("authored line break", "Two lines\nwritten deliberately"),
        ("apostrophes and dashes", "It didn't work - not once"),
        ("percentages", "50% faster, 3x cheaper"),
        ("unicode", "Ahmedabad -> London, 11 countries"),
    ]:
        case("Markup", name, False, slide({"role": "statement", "title": text}))

    # ── the claims policy ──
    for name, text in [
        ("prototype in 48 hours", "You'll have a working prototype in 48 hours."),
        ("ready in two weeks", "Your prototype is ready in two weeks."),
        ("same-day turnaround", "Same-day turnaround on the prototype."),
        ("by Friday", "We can ship it by Friday."),
        ("guaranteed delivery", "Guaranteed delivery in 10 days."),
        ("takes us four weeks", "It takes us about four weeks from brief to launch."),
        ("our price", "Our websites start at $5,000."),
        ("unattributed price", "A site like this costs about £8,000."),
        ("retainer", "Our retainer is £1,200 a month."),
        ("you'll pay", "You'll pay around $10k for something like this."),
    ]:
        case("Claims", name, True, claims.check(text))
    for name, text in [
        ("the free prototype", "We build a working prototype before any money changes hands."),
        ("no fee", "See it before you pay for it. No retainer, no discovery fee."),
        ("industry pricing", "Most agencies bill discovery as a paid phase."),
        ("industry comparison", "Typical agency retainers run into five figures a month."),
        ("industry delivery", "Most agencies take six months to get a first version out."),
        ("performance figure", "CuePilot answers in under 200ms on a mid-range phone."),
        ("company history", "We have been building software for three years."),
        ("someone else's money", "They raised $2m and still could not ship the app."),
        ("process, no duration", "You describe it, we build it, then you decide."),
    ]:
        case("Claims", name, False, claims.check(text))

    # ── grounding, both corpora ──
    for name, text in [
        ("invented percentage", "We increased conversions by 47% for a client."),
        ("invented project", "We built MediSyncPlus for a clinic."),
        ("invented client", "Our client Harrowgate Dental doubled bookings."),
        ("uncited external figure", "App store commissions dropped to 15% this week."),
    ]:
        case("Grounding", name, True, grounding.check(text, snapshot))
    for name, text in [
        ("real project", "We built CuePilot for Bellwether."),
        ("real figure", "Clients in 11 countries."),
        ("a place, not a client", "We rebuilt the booking flow for a clinic in Denver."),
        ("capitalised verb", "Confirms arrive by text now. We built that in an afternoon."),
        ("third party product", "Shopify put their commission up again."),
    ]:
        case("Grounding", name, False, grounding.check(text, snapshot))
    case("Grounding", "external figure WITH a captured source", False,
         grounding.check(
             "Commissions fell to 15% for small developers.", snapshot,
             [{"publisher": "The Register", "title": "Commission drop",
               "extract": "The rate falls to 15% for developers under $1,000,000 a year."}],
         ),
         "the same sentence is blocked with no source and allowed with one")

    # ── chart values go through grounding, not around it ──
    invented_chart = [{
        "role": "bar_chart", "title": "Where the time went",
        "chart": {"unit": "%", "series": [
            {"label": "Before", "value": 63}, {"label": "After", "value": 12},
            {"label": "Target", "value": 5}]},
    }]
    numbers = slide_gate.chart_numbers(invented_chart)
    case("Grounding", "chart with invented values", True,
         grounding.check(" ".join(numbers), snapshot),
         f"lifted from chart.series as {numbers}")
    grounded_chart = [{
        "role": "bar_chart", "title": "Reach",
        "chart": {"series": [{"label": "Countries", "value": 11},
                             {"label": "Projects", "value": 26},
                             {"label": "Tools", "value": 5}]},
    }]
    case("Grounding", "chart from the curated stats", False,
         grounding.check(" ".join(slide_gate.chart_numbers(grounded_chart)), snapshot),
         "11 / 26 / 5 all derive from the repo")

    # ── slide structure ──
    for name, d in [
        ("unknown role", {"role": "hero_banner", "title": "x"}),
        ("metric with no label", {"role": "metric_hero", "value": "200ms"}),
        ("stat_row with two tiles", {"role": "stat_row", "stats": [
            {"value": "26", "label": "a"}, {"value": "11", "label": "b"}]}),
        ("chart value as a string", {"role": "bar_chart", "title": "t", "chart": {"series": [
            {"label": "a", "value": "6s"}, {"label": "b", "value": 1},
            {"label": "c", "value": 2}]}}),
        ("donut over 100", {"role": "donut", "title": "t",
                            "chart": {"value": 140, "label": "of apps"}}),
        ("all bars zero", {"role": "bar_chart", "title": "t", "chart": {"series": [
            {"label": "a", "value": 0}, {"label": "b", "value": 0},
            {"label": "c", "value": 0}]}}),
        ("steps with two entries", {"role": "steps", "title": "t", "steps": [
            {"title": "one"}, {"title": "two"}]}),
        ("impossible layout", {"role": "quote", "quote": "q", "attribution": "a",
                               "layout": "full_bleed"}),
        ("theme not allowed", {"role": "statement", "title": "t", "theme": "neon"}),
        ("graphic_embed with no artwork", {"role": "graphic_embed", "kicker": "blog"}),
    ]:
        case("Structure", name, True, slide(d))
    case("Structure", "artwork supplied as inline svg", False,
         slide({"role": "graphic_embed", "svg": "<svg viewBox='0 0 1 1'></svg>"}),
         "the pipeline attaches `svg`; `image` is the other accepted form")
    case("Structure", "legacy role names still resolve", False,
         slide({"role": "cover", "title": "Nine no-shows, *gone*"}),
         "cover -> cover_bold, metric -> metric_hero, mockup -> mockup_browser, cta -> cta_pill")

    # ── fit budgets ──
    case("Fit", "metric value that would wrap", True,
         slide({"role": "metric_hero", "value": "1,240 hours saved", "label": "per year"}))
    case("Fit", "cover title over the h1 budget", True,
         slide({"role": "cover_bold",
                "title": "A dental clinic in Leeds was losing nine appointments every week"}))
    case("Fit", "the same title as a statement", False,
         slide({"role": "statement",
                "title": "A dental clinic in Leeds was losing nine appointments every week"}),
         "h2 is smaller, so its budget is larger - the budget is per archetype")

    # ── voice ──
    case("Voice", "banned phrases", True,
         voice.check("Let's dive in and unlock a seamless, game-changing experience."))
    case("Voice", "uniform sentence lengths", True, voice.check(
        "We help small businesses build software that works well for their teams. "
        "We focus on delivering value through careful planning and honest advice. "
        "We believe that good software should be simple and easy to maintain. "
        "We work closely with clients to understand what they actually need."))
    case("Voice", "short punchy copy", False, voice.check(
        "The booking page worked. Nobody used it. Six seconds to load on a phone. No reminder."),
        "varies 47% around a 4-word average")

    # ── platform limits ──
    case("Platform", "threads over 500 chars", True,
         platform_gate.check("threads", "x" * 520, [], 0))
    case("Platform", "pinterest over 500 chars", True,
         platform_gate.check("pinterest", "x" * 520, [], 1))
    case("Platform", "instagram hashtags in the caption", True,
         platform_gate.check("instagram", "A caption #SmallBusiness", ["SmallBusiness"], 6))
    case("Platform", "instagram with only 5 tags", True,
         platform_gate.check("instagram", "A caption.", ["a", "b", "c", "d", "e"], 6))
    for platform in ("instagram", "linkedin", "threads", "facebook", "x", "pinterest"):
        limits = LIMITS.get(platform)
        plan = deck_mod.DeckPlan(platform=platform, pillar="teach", recipe="x",
                                 region=regions.UK)
        for produced in (0, 5, 20):
            tags = deck_mod.hashtags(config, plan, produced)
            reasons = [r for r in platform_gate.check(platform, "A caption.", tags, 1)
                       if "hashtag" in r]
            case("Platform", f"{platform}: writer gave {produced} tags", False, reasons,
                 f"regional bank returned {len(tags)}"
                 + (f", limits {limits[3]}-{limits[4]}" if limits else ""))

    # ── artwork: the mismatch that shipped, and the shape of the fix ──
    from imaging import mockups

    def art_case(name, slide, expected, check, detail=""):
        plan_ = deck_mod.DeckPlan(
            platform="instagram", pillar="proof", recipe="proof_narrative",
            archetypes=["mockup_browser"], layouts=["centred"], themes=["light"],
        )
        got_ = deck_mod.decorate([slide], plan_, library=None, snapshot=snapshot)[0]
        actual, ok = check(got_)
        out.append({"group": "Artwork", "case": name, "expected": expected,
                    "actual": str(actual), "ok": ok, "why": "", "detail": detail})

    art_case(
        "a slide naming no known project",
        {"title": "Solar marketplace. *Live* in India.", "url": "wizcodes.site/work/solarsathi"},
        "a generated mockup, never another project's card",
        lambda g: (g.get("_art", "none"), str(g.get("_art", "")).startswith("mockup:")),
        "this exact slide shipped above a card reading 'Cine Duniya - ENTERTAINMENT'",
    )
    art_case(
        "a slide naming a real project",
        {"title": "CuePilot answers in *under 200ms*."},
        "the mockup for that project",
        lambda g: (g.get("_art", "none"), str(g.get("_art", "")).startswith("mockup:")),
        "matched by name; never guessed",
    )
    art_case(
        "a mobile project",
        {"title": "Cine Duniya in a thumb tap"},
        "mockup_phone",
        lambda g: (g["role"], g["role"] == "mockup_phone"),
        "ten of twenty-six projects are mobile; a browser frame misstates the work",
    )
    art_case(
        "a web project",
        {"title": "SolarSathi on the desk", "url": "wizcodes.site/work/solarsathi"},
        "mockup_browser",
        lambda g: (g["role"], g["role"] == "mockup_browser"),
    )
    textless = [k for k in mockups.KINDS if "<text" in mockups.by_kind(k).svg]
    out.append({
        "group": "Artwork", "case": "mockups contain no words at all",
        "expected": "none with text", "actual": str(textless or "none"),
        "ok": not textless, "why": "",
        "detail": "a picture with no words cannot make a claim that turns out false",
    })
    first = snapshot.projects[0]
    stable = mockups.for_project(first).kind == mockups.for_project(first).kind
    out.append({
        "group": "Artwork", "case": "the same project always draws the same product",
        "expected": "stable", "actual": "stable" if stable else "VARIES",
        "ok": stable, "why": "",
        "detail": "two posts about one project must not show two pieces of software",
    })

    plan = deck_mod.DeckPlan(platform="instagram", pillar="teach", recipe="visual_first",
                             archetypes=["graphic_embed"], layouts=["centred"], themes=["light"])
    got = deck_mod.decorate([{"title": "The four guardrails", "body": "A diagram."}], plan,
                            library=None, snapshot=snapshot)
    out.append({
        "group": "Artwork", "case": "graphic_embed with no diagram library",
        "expected": "statement", "actual": got[0]["role"],
        "ok": got[0]["role"] == "statement" and "svg" not in got[0],
        "why": "", "detail": "the only imaged archetype that still degrades to text",
    })

    # ── truncation ──
    from graph.nodes import _fallback_slide
    from platforms import Draft

    long_caption = (
        "Most agencies bill discovery as a paid phase. We build a working prototype "
        "before any money changes hands. Not a slideshow. A prototype you can click "
        "through, test with users, and show investors. Why? Because requirements do "
        "not survive first contact with a real screen."
    )
    fallback = _fallback_slide(Draft(platform="facebook", pillar="pov", caption=long_caption))
    clean = all(
        not fallback[f].strip() or fallback[f].strip()[-1] in ".!?" for f in ("title", "body")
    )
    out.append({
        "group": "Truncation", "case": "single-image fallback cuts on a sentence",
        "expected": "ends on . ! or ?", "actual": repr(fallback["body"][-38:]),
        "ok": clean, "why": "",
        "detail": "a published slide read 'Because requirements d' - it was a [:180] slice",
    })
    out.append({
        "group": "Truncation", "case": "the fallback slide passes the pre-render gate",
        "expected": "no reasons", "actual": str(slide_gate.check([fallback]) or "none"),
        "ok": not slide_gate.check([fallback]), "why": "", "detail": "",
    })

    # ── rotation ──
    used = [{"recipe": r.name, "archetypes": ["cover_bold", "statement"],
             "layouts": [], "theme": "light",
             "posted_at": datetime.now().astimezone() - timedelta(days=i)}
            for i, r in enumerate(recipes.RECIPES[:3])]
    picked, _, _, _ = recipes.pick(config, platform="instagram", pillar="teach", slides=5,
                                  has_stats=True, has_art=True, today=today_ist(), history=used)
    recent_names = {r["recipe"] for r in used}
    out.append({
        "group": "Rotation", "case": "recipe used in the last 14 days",
        "expected": f"not one of {sorted(recent_names)}", "actual": picked.name,
        "ok": picked.name not in recent_names, "why": "", "detail": "",
    })
    a = recipes.pick(config, platform="instagram", pillar="proof", slides=6,
                     has_stats=True, has_art=True, today=date(2026, 8, 10), history=[])
    b = recipes.pick(config, platform="instagram", pillar="proof", slides=6,
                     has_stats=True, has_art=True, today=date(2026, 8, 10), history=[])
    out.append({
        "group": "Rotation", "case": "same slot, same day, run twice",
        "expected": "identical deck", "actual": "identical" if a[1] == b[1] else "DIFFERENT",
        "ok": a[1] == b[1] and a[0].name == b[0].name, "why": "",
        "detail": "a retry must not re-roll under an idempotency key that says done",
    })
    everything = [{"recipe": r.name, "archetypes": ["cover_bold"], "layouts": [],
                   "theme": "light", "posted_at": datetime.now().astimezone()}
                  for r in recipes.RECIPES]
    still = recipes.pick(config, platform="instagram", pillar="teach", slides=5,
                         has_stats=True, has_art=True, today=today_ist(), history=everything)
    out.append({
        "group": "Rotation", "case": "every recipe already used this fortnight",
        "expected": "still returns a deck", "actual": still[0].name,
        "ok": bool(still[0] and len(still[1]) == 5), "why": "",
        "detail": "refusing to publish over a bookkeeping preference is the wrong trade",
    })

    # ── phasing ──
    # Revised 9 Aug 2026. The launch withholds ONE pillar for two weeks, not
    # three for six. Credibility already exists on the website, and timely is the
    # best discovery mechanism a new account has.
    for pillar, when, expect in [
        ("direct_offer", "launch", "substituted"),
        ("timely", "launch", "kept"),
        ("pov", "launch", "kept"),
        ("proof", "launch", "kept"),
        ("client_voice", "launch", "kept"),
        ("direct_offer", "compound", "kept"),
        ("timely", "compound", "kept"),
        ("direct_offer", "full", "kept"),
    ]:
        start = today_ist() - timedelta(days=PHASE_START[when])
        got_pillar = phase.substitute(pillar, start, today_ist())
        actual = "kept" if got_pillar == pillar else "substituted"
        out.append({
            "group": "Phasing", "case": f"{pillar} in phase '{when}'",
            "expected": expect, "actual": f"{actual} -> {got_pillar}",
            "ok": actual == expect, "why": "", "detail": "",
        })

    # ── capacity ceilings ──
    for platform, plan_ in capacity.DEFAULTS.items():
        rows = capacity.ramp_schedule(platform, today_ist(), weeks=12)
        peak = max((t for _, t in rows), default=0)
        out.append({
            "group": "Capacity", "case": f"{platform} 12-week ramp",
            "expected": f"peak <= {plan_.ceiling:g}/day", "actual": f"{peak:g}/day",
            "ok": peak <= plan_.ceiling, "why": "",
            "detail": f"launch {plan_.launch:g} -> steady {plan_.steady:g}, {len(rows)} step(s)",
        })

    # ── geography ──
    for hour, expect in [(13, ("GB", "EU")), (20, ("US",)), (12, ("EU",)), (16, ("GB",))]:
        got_region = regions.for_slot("instagram", hour, date(2026, 8, 10)).code
        out.append({
            "group": "Geography", "case": f"a slot at {hour:02d}:00 IST",
            "expected": " or ".join(expect), "actual": got_region,
            "ok": got_region in expect, "why": "",
            "detail": {"GB": "09:00 BST", "US": "09:00 ET", "EU": "09:00 CET"}.get(got_region, ""),
        })
    banks = [set(r.queries) for r in regions.REGIONS]
    out.append({
        "group": "Geography", "case": "query banks are written, not translated",
        "expected": "no shared queries", "actual": "shared: " + str(
            sum(len(a & b) for i, a in enumerate(banks) for b in banks[i + 1:])),
        "ok": all(not (a & b) for i, a in enumerate(banks) for b in banks[i + 1:]),
        "why": "", "detail": "",
    })

    # ── registry invariants ──
    bad = [a.name for a in visual.ARCHETYPES
           if not set(a.layouts) <= set(visual.LAYOUTS) or (a.imaged and not a.fallback)]
    out.append({
        "group": "Registry", "case": "every archetype is renderable",
        "expected": "none broken", "actual": str(bad or "none"),
        "ok": not bad, "why": "",
        "detail": f"{len(visual.ARCHETYPES)} archetypes, {len(visual.LAYOUTS)} layouts, "
                  f"{len(visual.THEMES)} themes",
    })
    bad_recipes = [r.name for r in recipes.RECIPES
                   if not all(visual.resolve(x) for x in r.shape)]
    out.append({
        "group": "Registry", "case": "every recipe uses real archetypes",
        "expected": "none broken", "actual": str(bad_recipes or "none"),
        "ok": not bad_recipes, "why": "",
        "detail": f"{len(recipes.RECIPES)} recipes",
    })
    return out


# ══════════════════════════════════════════════════════════════════════════════
# The report
# ══════════════════════════════════════════════════════════════════════════════
CSS = """
:root{color-scheme:light dark;--bg:#fff;--fg:#101828;--muted:#667085;--line:#e4e7ec;
 --accent:#2E90C4;--ok:#05603a;--okbg:#d1fadf;--bad:#b42318;--badbg:#fee4e2;--warnbg:#fef0c7}
@media(prefers-color-scheme:dark){:root{--bg:#0b1220;--fg:#e6edf5;--muted:#9fb0c4;--line:#1e2a3a;
 --ok:#a6f4c5;--okbg:#054f31;--bad:#fda29b;--badbg:#5b1a16;--warnbg:#7a2e0e}}
*{box-sizing:border-box}
body{margin:0;padding:28px;background:var(--bg);color:var(--fg);max-width:1180px;margin-inline:auto;
 font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
h1{font-size:1.7rem;margin:0 0 4px}
h2{font-size:1.15rem;margin:38px 0 6px;padding-bottom:6px;border-bottom:2px solid var(--accent)}
h3{font-size:.95rem;margin:26px 0 8px;color:var(--accent);text-transform:uppercase;letter-spacing:.04em}
.sum{color:var(--muted);margin:0 0 6px}
.cov{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 6px}
.cov div{border:1px solid var(--line);border-radius:10px;padding:8px 12px;font-size:.85rem}
.cov b{color:var(--accent)}
.card{border:1px solid var(--line);border-radius:14px;padding:18px;margin:16px 0}
.card.fail{border-color:#f97066}.card.skip{opacity:.62}
.hd{font-size:.95rem;font-weight:600;margin:0 0 8px}
.pill{font-size:.7rem;background:var(--line);color:var(--muted);padding:2px 8px;border-radius:99px;margin-left:6px}
.pill.ok{background:var(--okbg);color:var(--ok)}.pill.warn{background:var(--warnbg)}
.pill.bad{background:var(--badbg);color:var(--bad)}
.design{font-size:.84rem;color:var(--muted);margin:0 0 10px}
.design b{color:var(--accent)}
.shape{font-family:ui-monospace,Menlo,monospace;font-size:.76rem}
pre.caption{white-space:pre-wrap;font:inherit;margin:0 0 8px}
.tags{color:var(--accent);font-size:.88rem;margin:0 0 6px}
.shots{display:flex;gap:10px;overflow-x:auto;padding-top:8px}
.shots img{height:300px;border-radius:10px;border:1px solid var(--line);flex:0 0 auto;background:#fff}
ul.why{margin:8px 0 0;padding-left:18px;font-size:.82rem;color:var(--muted)}
ul.why .bad{color:#f97066}
table{width:100%;border-collapse:collapse;font-size:.84rem;margin-top:6px}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:.76rem;text-transform:uppercase;letter-spacing:.04em}
td.v{white-space:nowrap;font-weight:600}
td.v.pass{color:var(--ok)}td.v.fail{color:var(--bad)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:14px}
.tile{border:1px solid var(--line);border-radius:12px;overflow:hidden}
.tile img{width:100%;display:block;background:#fff}
.tile .lbl{padding:7px 9px;font-size:.72rem;color:var(--muted);font-family:ui-monospace,Menlo,monospace}
.tile.bad{border-color:#f97066}
.note{background:var(--warnbg);border-radius:10px;padding:12px 14px;font-size:.86rem;margin:14px 0}
"""


def write_report(out_dir: Path, config, posts, matrix, guards, meta) -> None:
    esc = html.escape
    blocks: list[str] = []

    # ── coverage ──
    recipes_used = sorted({p["recipe"] for p in posts if p.get("recipe")})
    regions_used = sorted({p["region"] for p in posts if p.get("region")})
    phases_used = sorted({p["phase"] for p in posts if p.get("phase")})
    arch_used = sorted({a for p in posts for a in (p.get("archetypes") or [])})
    passed = sum(1 for p in posts if p.get("caption"))
    imgs = sum(len(p.get("images", [])) for p in posts) + sum(1 for m in matrix if m.get("image"))
    post_errs = sum(len(a.get("errors", [])) for p in posts for a in (p.get("audit") or []))
    mat_errs = sum(len((m.get("audit") or {}).get("errors", [])) for m in matrix)
    guard_fail = [g for g in guards if not g["ok"]]

    if posts:
        blocks.append("<div class='cov'>"
                      f"<div><b>{passed}/{len(posts)}</b> posts passed all six gates</div>"
                      f"<div><b>{len(recipes_used)}/8</b> recipes</div>"
                      f"<div><b>{len(arch_used)}</b> archetypes</div>"
                      f"<div><b>{len(regions_used)}</b> regions</div>"
                      f"<div><b>{len(phases_used)}</b> phases</div>"
                      f"<div><b>{imgs}</b> images</div>"
                      f"<div><b>{post_errs + mat_errs}</b> render audit errors</div>"
                      f"<div><b>{len(guards) - len(guard_fail)}/{len(guards)}</b> guardrails</div>"
                      "</div>")

    # ── A. generated posts ──
    if posts:
        blocks.append("<h2>A. Generated posts — the real pipeline</h2>")
        blocks.append("<p class='sum'>Same prompts, same six validators, same renderer a "
                      "scheduled run uses. Publishing is the only step skipped.</p>")
        for p in posts:
            head = (f"{p['platform']} · {p['pillar']} · {p['fmt']}"
                    f" · {p['phase']} phase · {p.get('hour_ist', 0):02d}:00 IST")
            if p.get("skipped"):
                blocks.append(f"<section class='card skip'><p class='hd'>{esc(head)}</p>"
                              f"<p class='sum'>skipped — {esc(p['skipped'])}</p></section>")
                continue
            tries = len(p.get("attempts", []))
            badge = ("<span class='pill ok'>first try</span>" if tries == 1
                     else f"<span class='pill warn'>{tries} attempts</span>")
            if p.get("failed"):
                badge = f"<span class='pill bad'>rejected after {tries}</span>"
            sub = (f" · <b>{esc(p['substituted_from'])} withheld → {esc(p['pillar'])}</b>"
                   if p.get("substituted_from") else "")
            kw = (f"<br>search phrase [{esc(p.get('phrase_tier', ''))}]: "
                  f"<b>{esc(p.get('phrase', ''))}</b>"
                  f"<br><span class='shape'>slug: {esc(p.get('slug', ''))}</span>"
                  if p.get("phrase") else "")
            req = " (requested)" if p.get("requested_recipe") else " (chosen by the ledger)"
            design = (f"<p class='design'><b>{esc(p['recipe'])}</b>{esc(req)} · "
                      f"{esc(p['region'])} {esc(p.get('locale', ''))}{sub}<br>"
                      f"<span class='shape'>{esc(' → '.join(p.get('archetypes') or []))}</span><br>"
                      f"<span class='shape'>{esc(' · '.join(p.get('layouts') or []))}</span>"
                      f"{kw}</p>")
            why = []
            for a in p.get("attempts", []):
                for r in (a.get("reasons") or []):
                    why.append(f"<li>attempt {a['attempt']}: {esc(str(r))}</li>")
                if a.get("error"):
                    why.append(f"<li class='bad'>attempt {a['attempt']}: {esc(a['error'])}</li>")
            for a in (p.get("audit") or []):
                for e in a.get("errors", []):
                    why.append(f"<li class='bad'>render, slide {a.get('slide')}: {esc(str(e))}</li>")
                for w in a.get("warnings", []):
                    why.append(f"<li>render, slide {a.get('slide')}: {esc(str(w))}</li>")
            imgs_html = "".join(
                f"<img src='{esc(i)}' loading='lazy' alt=''>" for i in p.get("images", []))
            angle = (f"<p class='sum'>Trend angle: {esc(p['angle'])}<br>"
                     f"Source (first comment): {esc(p.get('citation') or '')}</p>"
                     if p.get("angle") else "")
            blocks.append(
                f"<section class='card{' fail' if p.get('failed') else ''}'>"
                f"<p class='hd'>{esc(head)} {badge}"
                f"<span class='pill'>{len(p.get('caption', ''))} chars</span></p>"
                f"{design}{angle}"
                f"<pre class='caption'>{esc(p.get('caption', ''))}</pre>"
                f"<p class='tags'>{esc(' '.join('#' + t.lstrip('#') for t in p.get('hashtags', [])))}</p>"
                f"<div class='shots'>{imgs_html}</div>"
                f"{'<ul class=why>' + ''.join(why) + '</ul>' if why else ''}"
                "</section>")

    # ── B. visual matrix ──
    if matrix:
        blocks.append("<h2>B. Visual matrix — every archetype in every layout</h2>")
        blocks.append(f"<p class='sum'>{len(matrix)} combinations, fixed copy so two runs are "
                      "comparable. Themes rotate across the set.</p>")
        for family in ("opener", "data", "explainer", "proof", "closer"):
            rows = [m for m in matrix if m["family"] == family]
            if not rows:
                continue
            blocks.append(f"<h3>{family}</h3><div class='grid'>")
            for m in rows:
                errs = (m.get("audit") or {}).get("errors") or []
                warns = (m.get("audit") or {}).get("warnings") or []
                fit = (m.get("audit") or {}).get("fit")
                extra = f" · fit {fit}" if fit and fit != 1 else ""
                blocks.append(
                    f"<div class='tile{' bad' if errs else ''}'>"
                    f"<img src='{esc(m['image'])}' loading='lazy' alt=''>"
                    f"<div class='lbl'>{esc(m['role'])}<br>{esc(m['layout'])} · "
                    f"{esc(m['theme'])}{esc(extra)}"
                    + (f"<br><span style='color:#f97066'>{esc(errs[0][:60])}</span>" if errs else "")
                    + (f"<br>{esc(warns[0][:60])}" if warns and not errs else "")
                    + "</div></div>")
            blocks.append("</div>")

    # ── C. guardrails ──
    if guards:
        blocks.append("<h2>C. Guardrails — every edge case</h2>")
        blocks.append("<p class='sum'>Deterministic. This is the section to diff between "
                      "runs.</p>")
        if guard_fail:
            blocks.append("<div class='note'><b>"
                          f"{len(guard_fail)} guardrail(s) did not behave as expected.</b></div>")
        groups: dict[str, list[dict]] = {}
        for g in guards:
            groups.setdefault(g["group"], []).append(g)
        for name, rows in groups.items():
            bad = sum(1 for r in rows if not r["ok"])
            blocks.append(f"<h3>{esc(name)} — {len(rows) - bad}/{len(rows)}</h3>"
                          "<table><tr><th>case</th><th>expected</th><th>actual</th>"
                          "<th>what the gate said</th></tr>")
            for r in rows:
                cls = "pass" if r["ok"] else "fail"
                detail = f"<br><span style='opacity:.7'>{esc(r['detail'])}</span>" if r["detail"] else ""
                blocks.append(
                    f"<tr><td>{esc(r['case'])}{detail}</td><td>{esc(r['expected'])}</td>"
                    f"<td class='v {cls}'>{esc(r['actual'])}</td>"
                    f"<td style='color:var(--muted)'>{esc(r['why'])}</td></tr>")
            blocks.append("</table>")

    (out_dir / "index.html").write_text(
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>WizCodes content — end-to-end review</title>"
        f"<style>{CSS}</style></head><body>"
        "<h1>WizCodes content — end-to-end review</h1>"
        f"<p class='sum'>{meta['when']} · model {esc(meta['model'])} via "
        f"{esc(meta['proxy'])} · site facts from {esc(meta['facts'])} · "
        f"<strong>nothing was published</strong></p>"
        + "".join(blocks) + "</body></html>",
        encoding="utf-8",
    )
    (out_dir / "results.json").write_text(
        json.dumps({"meta": meta, "posts": posts, "matrix": matrix, "guardrails": guards},
                   indent=2, default=str),
        encoding="utf-8",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="One deliberate end-to-end run")
    ap.add_argument("--posts", type=int, default=len(CASES), help="how many generated posts")
    ap.add_argument("--only", default="", choices=["", "posts", "visual", "guards"])
    args = ap.parse_args()

    from wizcore.obs.log import setup_logging

    from config import AGENT_NAME, CONFIG

    # Forced, not defaulted. This tool is meant to be run casually while
    # reviewing, and a review that could publish is not a review.
    config = dataclasses.replace(CONFIG, dry_run=True)
    setup_logging(AGENT_NAME, "e2e", "ERROR")

    # Assert the proxy rather than assume it. "Only the Claude proxy" is a
    # property of this run that the reader should be able to trust.
    if config.llm_provider != "proxy":
        print(f"LLM_PROVIDER is {config.llm_provider!r}, expected 'proxy'", file=sys.stderr)
        return 2
    import os

    base = os.environ.get("ANTHROPIC_BASE_URL", "")
    if not base:
        print("ANTHROPIC_BASE_URL is not set", file=sys.stderr)
        return 2

    stamp = datetime.now(ZoneInfo(config.display_tz)).strftime("%Y%m%d_%H%M")
    out_dir = AGENT_ROOT / "output" / f"e2e_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"→ {out_dir}\n  proxy {base}  model {config.voice_model}\n")

    posts, matrix, guards = [], [], []
    if args.only in ("", "posts"):
        posts = generate(config, CASES[: args.posts], out_dir)
    if args.only in ("", "visual"):
        matrix = visual_matrix(config, out_dir)
    if args.only in ("", "guards"):
        from wizcore.facts.site import SiteReader
        from wizcore.facts.snapshot import build_snapshot

        snapshot = build_snapshot(SiteReader(
            repo=config.site_repo, token=config.site_read_token,
            ref=config.site_branch, local_dir=config.site_local_dir or None,
        ))
        print("[C] running guardrail cases ...", flush=True)
        guards = guardrails(config, snapshot, out_dir)

    write_report(out_dir, config, posts, matrix, guards, {
        "when": datetime.now(ZoneInfo(config.display_tz)).strftime("%d %b %Y %H:%M %Z"),
        "model": config.voice_model,
        "proxy": base,
        "facts": config.site_local_dir or f"{config.site_repo}@{config.site_branch}",
    })

    bad_guards = [g for g in guards if not g["ok"]]
    print(f"\n  posts      {sum(1 for p in posts if p.get('caption'))}/{len(posts)} passed")
    print(f"  visual     {len(matrix)} combinations, "
          f"{sum(1 for m in matrix if (m.get('audit') or {}).get('errors'))} with errors")
    print(f"  guardrails {len(guards) - len(bad_guards)}/{len(guards)} as expected")
    for g in bad_guards:
        print(f"    FAIL {g['group']}/{g['case']}: expected {g['expected']}, got {g['actual']}")
    print(f"\n  open: {out_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
