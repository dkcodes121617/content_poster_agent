"""Real decks through the v2 design engine, for review. Nothing is published.

    python tools/design_e2e.py                       all cases (LLM via the proxy)
    python tools/design_e2e.py --cases 3             the first three
    modal run modal_app.py::render_cli --items output/design_e2e_<stamp>/items.json

The first command writes drafts locally - the planner (design/select.py), the
prompt (design/prompt.py), the strict parser and every production gate, with
the same regenerate-on-rejection loop the write node uses. The second renders
them on Modal; Chromium never runs on this machine.

Nothing is recorded in content.visual_history: a review run is not a fortnight
of publishing, and recording it would make the real rotation think it had
already shown these looks. The rotation is simulated in memory instead, so the
cases still exercise "never the same look twice in a row".
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

AGENT_ROOT = Path(__file__).resolve().parent.parent
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))
for _stream in (sys.stdout, sys.stderr):
    with __import__("contextlib").suppress(AttributeError, ValueError):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# (platform, pillar, slides) - spread so carousels, singles, every canvas and
# most recipes are covered rather than whatever the rotation picks today.
CASES: list[tuple[str, str, int]] = [
    ("linkedin", "teach", 8),
    ("instagram", "pov", 7),
    ("linkedin", "proof", 8),
    ("instagram", "process", 7),
    ("pinterest", "teach", 1),
    ("linkedin", "direct_offer", 6),
    ("facebook", "proof", 1),
    ("instagram", "client_voice", 6),
    ("linkedin", "pov", 9),
    ("instagram", "teach", 8),
]


def generate(config, cases, out_dir: Path, salt: str = "") -> tuple[list[dict], list]:
    from wizcore.facts.site import SiteReader
    from wizcore.facts.snapshot import build_snapshot
    from wizcore.llm.client import LLMClient

    from campaign.calendar import today_ist
    from design import gates, prompt, select
    from design.render import build_payload

    reader = SiteReader(repo=config.site_repo, token=config.site_read_token,
                        ref=config.site_branch, local_dir=config.site_local_dir or None)
    snapshot = build_snapshot(reader)
    facts = snapshot.to_prompt_block(include_testimonials=True)
    system = prompt.system(facts, snapshot.stats_block())
    client = LLMClient(model=config.voice_model)
    today = today_ist(config.display_tz)
    has_stats = bool(snapshot.chartable_stats())
    ledger: dict[str, list[dict]] = {}

    report: list[dict] = []
    items: list = []
    for n, (platform, pillar, slides) in enumerate(cases, 1):
        plan = select.plan(platform=platform, pillar=pillar, slides=slides, history=ledger.get(platform, []),
                           today=today, slot_key=f"e2e{salt}-{n}", has_stats=has_stats, has_project=bool(snapshot.projects))
        print(f"[{n}/{len(cases)}] {platform}/{pillar}: {plan.brief()}", flush=True)
        user = prompt.user(plan, platform=platform, pillar=pillar)

        def check(draft, _platform=platform, _pillar=pillar, _count=len(plan.slides)):
            return gates.check(draft, platform_name=_platform, snapshot=snapshot, sources=[], pillar=_pillar,
                               image_count=_count, repetition_threshold=config.repetition_threshold)

        def show(a):
            first = f" - {a['problems'][0][:150]}" if a["problems"] else ""
            print(f"    call {a['call']} ({a['mode']}): {len(a['problems'])} problem(s) in {a['seconds']}s{first}", flush=True)

        draft, problems, attempts = prompt.write(client, system=system, user=user, plan=plan, snapshot=snapshot,
                                                 gates=check, on_attempt=show)
        ok = draft is not None and not problems
        report.append({"case": n, "platform": platform, "pillar": pillar, "plan": plan.to_record(),
                       "ok": ok, "attempts": attempts, "problems": problems, "draft": draft})
        if not ok or draft is None:
            continue
        ledger.setdefault(platform, []).insert(0, {"recipe": plan.recipe, "design": plan.to_record()})
        count = len(plan.slides)
        for i, (choice, slide) in enumerate(zip(plan.choices(), draft["slides"], strict=False), 1):
            svg = _mockup_svg(slide, snapshot) if slide["format"] == "mockup" else None
            payload = build_payload(choice, slide["content"], canvas=plan.canvas,
                                    slide={"index": i, "count": count} if count > 1 else None, svg=svg)
            items.append((f"{n:02d}.{i:02d} {platform}/{pillar} {plan.recipe} {slide['format']}/{choice.layout}/{plan.look}/{plan.accent}/{plan.art}", payload))
    return report, items


def _mockup_svg(slide: dict, snapshot) -> str | None:
    """A generated mockup for the named project (the production path)."""
    from imaging import mockups

    project = snapshot.project_by_slug(str(slide["content"].get("project") or ""))
    if project is None:
        return None
    try:
        return mockups.for_project(project).svg
    except Exception:  # artwork is an enhancement, never a failure
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Real decks through the v2 design engine")
    ap.add_argument("--cases", type=int, default=len(CASES))
    ap.add_argument("--salt", default="", help="varies the seeded designs between review runs")
    args = ap.parse_args()

    from wizcore.obs.log import setup_logging

    from config import AGENT_NAME, CONFIG

    config = dataclasses.replace(CONFIG, dry_run=True)
    setup_logging(AGENT_NAME, "design_e2e", "ERROR")
    stamp = datetime.now(ZoneInfo(config.display_tz)).strftime("%Y%m%d_%H%M")
    out_dir = AGENT_ROOT / "output" / f"design_e2e_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"-> {out_dir}  model {config.voice_model}\n", flush=True)

    report, items = generate(config, CASES[: args.cases], out_dir, args.salt)
    (out_dir / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    (out_dir / "items.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    ok = sum(1 for r in report if r["ok"])
    print(f"\n{ok}/{len(report)} decks passed every gate; {len(items)} slides queued for rendering")
    print(f"render: modal run modal_app.py::render_cli --items {out_dir / 'items.json'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
