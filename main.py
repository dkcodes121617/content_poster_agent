"""Content Poster entry point.

    python main.py                  publish whatever the calendar says is due now
    python main.py --dry-run        render and validate, publish nothing
    python main.py --force facebook:proof   ignore the calendar, do one slot now
    python main.py --schedule       print the week and exit
    python main.py --brief          send the daily Telegram brief now
"""
from __future__ import annotations

import argparse
import contextlib
import logging
import sys
import uuid

from wizcore.db.runs import run_scope
from wizcore.db.spend import BudgetGuard
from wizcore.obs.log import log_event, setup_logging
from wizcore.telegram.send import alert

from campaign.calendar import WEEK, Slot, ist_now
from config import AGENT_NAME, CONFIG

log = logging.getLogger("content_poster")


def run_once(config=CONFIG, run_id: str | None = None, forced: list[Slot] | None = None) -> dict:
    run_id = run_id or str(uuid.uuid4())
    setup_logging(AGENT_NAME, run_id, config.log_level)

    from graph.build import build_graph, make_checkpointer

    log_event(
        log, "run.start",
        dry_run=config.dry_run, platforms=",".join(config.active_platforms()),
    )

    budget = BudgetGuard.load(AGENT_NAME, config.budget_caps, config.database_url)
    checkpointer = make_checkpointer(config)

    try:
        with run_scope(AGENT_NAME, run_id, config.database_url) as recorder:
            graph = build_graph(config, budget, checkpointer, forced=forced)
            final = graph.invoke(
                {"run_id": run_id},
                config={"configurable": {"thread_id": run_id}},
                # "sync", unlike the Lead Finder. This agent publishes, and a
                # checkpoint written after an irreversible action is a
                # checkpoint that cannot prevent repeating it.
                durability="sync",
            )
            counters = final.get("counters") or {}
            recorder.set(**{k: v for k, v in counters.items() if isinstance(v, int)})
            if counters.get("publish_failed") or counters.get("rejected"):
                recorder.mark_partial("some platforms failed or drafts were rejected")
            log_event(log, "run.done", **{k: v for k, v in counters.items() if isinstance(v, int)})
            return counters
    except Exception as exc:
        log.exception("run failed")
        alert(AGENT_NAME, exc)
        raise
    finally:
        budget.flush()
        if checkpointer is not None:
            with contextlib.suppress(Exception):
                checkpointer.conn.close()


def print_schedule() -> None:
    """The week, plus everything that now modifies it.

    The calendar alone stopped being the whole answer once phasing could
    substitute a pillar and geography could decide who a slot is written for.
    Printing the slots without those would show a schedule the agent no longer
    follows.
    """
    from campaign import capacity, phase, regions
    from campaign.calendar import today_ist

    today = today_ist(CONFIG.display_tz)
    start = CONFIG.start_date()
    print(phase.describe(start, today))
    current = phase.current(start, today)
    print(f"  {current.note}")
    print("  mix: " + ", ".join(f"{k} {v:.0%}" for k, v in
                                 sorted(current.mix.items(), key=lambda kv: -kv[1])))
    print()

    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    print("Weekly rhythm (IST, jittered +/-25 min at run time):\n")
    for index, day in enumerate(days):
        slots = [s for s in WEEK if s.weekday == index]
        if not slots:
            print(f"  {day}  - (empty by design: seven-day posting reads as automated)")
            continue
        for slot in sorted(slots, key=lambda s: (s.hour, s.minute)):
            extra = f" x{slot.slides}" if slot.slides else ""
            effective = phase.substitute(slot.pillar, start, today)
            pillar = (
                f"{effective} (was {slot.pillar})" if effective != slot.pillar else slot.pillar
            )
            region = (
                regions.for_slot(slot.platform, slot.hour, today).code
                if CONFIG.geo_targeting else "--"
            )
            print(f"  {day}  {slot.hour:02d}:{slot.minute:02d}  {region:<3} "
                  f"{slot.platform:<10} {pillar:<22} {slot.fmt}{extra}")

    if CONFIG.capacity_scheduling:
        print("\nPosting plan (targets per day):")
        for line in capacity.describe(CONFIG, CONFIG.active_platforms(), today):
            print(line)


def main() -> int:
    parser = argparse.ArgumentParser(description="WizCodes Content Poster")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--schedule", action="store_true", help="print the week and exit")
    parser.add_argument("--force", default="",
                        help="platform:pillar[:fmt[:slides]] - run one slot regardless of time")
    parser.add_argument("--syndicate", action="store_true",
                        help="syndicate the newest un-syndicated blog post to dev.to")
    parser.add_argument("--trends", default="", metavar="harvest|refine|full|status",
                        help="run the trend pipeline, or show the funnel")
    parser.add_argument("--brief", action="store_true",
                        help="send the daily Telegram brief now and exit")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.schedule:
        print_schedule()
        return 0

    if args.brief:
        import uuid as _uuid

        from campaign import brief

        setup_logging(AGENT_NAME, str(_uuid.uuid4()), CONFIG.log_level)
        print(brief.compose(CONFIG))
        print()
        for key, value in brief.send_daily(CONFIG).items():
            print(f"  {key:22} {value}")
        return 0

    import dataclasses

    config = CONFIG
    overrides = {}
    if args.dry_run:
        overrides["dry_run"] = True
    if args.verbose:
        overrides["log_level"] = "DEBUG"
    if overrides:
        config = dataclasses.replace(config, **overrides)

    if args.trends:
        import uuid as _uuid

        from wizcore.db.spend import BudgetGuard

        from trends import run as trends_run

        setup_logging(AGENT_NAME, str(_uuid.uuid4()), config.log_level)
        if args.trends == "status":
            print(trends_run.summary(config))
            return 0
        budget = BudgetGuard.load(AGENT_NAME, config.budget_caps, config.database_url)
        try:
            fn = {"harvest": trends_run.harvest_only, "refine": trends_run.refine,
                  "full": trends_run.full}.get(args.trends)
            if not fn:
                print(f"unknown --trends mode {args.trends!r}", file=sys.stderr)
                return 2
            result = fn(config) if fn is trends_run.harvest_only else fn(config, budget)
            for key, value in result.items():
                print(f"  {key:22} {value}")
        finally:
            budget.flush()
        print()
        print(trends_run.summary(config))
        return 0

    if args.syndicate:
        import uuid as _uuid

        from campaign import syndicate

        setup_logging(AGENT_NAME, str(_uuid.uuid4()), config.log_level)
        for key, value in syndicate.run(config).items():
            print(f"  {key:22} {value}")
        return 0

    forced = None
    if args.force:
        parts = args.force.split(":")
        if len(parts) < 2:
            print("--force needs platform:pillar", file=sys.stderr)
            return 2
        now = ist_now(config.display_tz)
        forced = [
            Slot(
                weekday=now.weekday(), hour=now.hour, minute=now.minute,
                platform=parts[0], pillar=parts[1],
                fmt=parts[2] if len(parts) > 2 else "single",
                slides=int(parts[3]) if len(parts) > 3 else 0,
            )
        ]

    try:
        counters = run_once(config, forced=forced)
    except Exception as e:
        print(f"\nFAILED: {e}", file=sys.stderr)
        return 1

    print("\n--- run summary ---")
    for key in sorted(counters):
        print(f"  {key:20} {counters[key]}")
    if config.dry_run:
        print("\n  DRY_RUN=1 - images were rendered, nothing was published.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
