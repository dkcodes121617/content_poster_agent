"""Content Poster nodes.

The shape is a straight line — plan, write, validate, render, publish, record —
because the work genuinely is one. What the graph buys here is not branching but
**durability**: `durability="sync"` means the checkpoint is written before each
irreversible step, and a container killed mid-run resumes rather than restarts.
A checkpoint written *after* an irreversible action is a checkpoint that cannot
prevent repeating it.
"""
from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime

from wizcore.db.actions import claim, make_key
from wizcore.db.conn import connect
from wizcore.facts.site import SiteReader
from wizcore.facts.snapshot import build_snapshot
from wizcore.llm.client import LLMClient, extract_json
from wizcore.obs.log import log_event
from wizcore.telegram.send import esc, send, send_album, send_photo

from campaign.calendar import due_slots, ist_now
from config import AGENT_NAME
from imaging import r2, render
from platforms import Draft, PublishResult, get_platform
from prompts.library import REGENERATE_NOTE, post_system_prompt, post_user_prompt
from validators import repetition, validate

log = logging.getLogger("content_poster.graph")


def make_reader(config) -> SiteReader:
    """One reader per run. It caches, so rebuilding the snapshot is free.

    The snapshot itself deliberately never enters graph state: it carries a
    ~70 KB playbook excerpt, and the checkpointer would serialise that into
    Postgres on every single step. The reader is shared by closure instead, and
    each node that needs facts rebuilds them from its cache — regex over strings
    already in memory, no network.
    """
    return SiteReader(
        repo=config.site_repo,
        token=config.site_read_token,
        ref=config.site_branch,
        local_dir=config.site_local_dir or None,
    )


def _process_commands(config) -> dict:
    """`/done <id>` for the X and YouTube hand-off queue.

    Polled inside the scheduled run rather than via a webhook — this system has
    exactly one public HTTPS endpoint by design, and it is not for this. A
    command taking up to an hour to register is fine; the alternative is a
    second public surface to secure.
    """
    from wizcore.db.conn import connect
    from wizcore.telegram.send import poll_commands

    from platforms.manual import mark_done

    counters = {"cmd_done": 0}
    try:
        commands = poll_commands()
    except Exception:
        log.warning("could not poll Telegram commands", exc_info=True)
        return counters
    replies = []
    for cmd in commands:
        if cmd["command"] != "done" or not cmd["args"].strip().isdigit():
            continue
        queue_id = int(cmd["args"].strip())
        try:
            with connect(config.database_url) as conn:
                ok = mark_done(conn, queue_id)
        except Exception:
            log.warning("could not mark manual item %s done", queue_id, exc_info=True)
            continue
        counters["cmd_done"] += int(ok)
        replies.append(
            f"✅ manual item {queue_id} marked posted" if ok
            else f"❓ {queue_id} is not a pending manual item"
        )
    if replies:
        send("\n".join(replies), topic="content", dry_run=False, silent=True)
    return counters


def _timely_slot(config, now, busy: set):
    """A timely slot for the best platform with budget left today, or None.

    Returns None far more often than not, which is correct: most hours have no
    angle worth interrupting the schedule for, and an agent that inserts
    whenever it can stops having a rhythm at all.
    """
    from campaign.calendar import TIMELY_PLATFORMS, timely_slot
    from trends import angle as angle_mod

    for platform in TIMELY_PLATFORMS:
        if platform in busy or platform not in config.active_platforms():
            continue
        if not angle_mod.insert_available(config, platform):
            continue
        if not angle_mod.ready_angle(config, platform):
            continue
        log.info("timely insert available for %s", platform)
        return timely_slot(platform, now)
    return None


def make_preflight(config, reader: SiteReader, forced: list | None = None):
    def preflight(state):
        config.validate()
        snapshot = build_snapshot(reader)
        if not snapshot.projects:
            # Refusing here is the point of the grounding gate existing at all:
            # with no real projects the writer has nothing true to say, and
            # every "proof" post it produced would be invented.
            raise RuntimeError(
                "site facts contain no projects - refusing to publish ungrounded content"
            )

        counters = _process_commands(config)

        now = ist_now(config.display_tz)
        # `--force` bypasses the calendar for a single named slot. It bypasses
        # the calendar and nothing else: the validators, the idempotency claim
        # and DRY_RUN all still apply, because the calendar is scheduling, not
        # safety.
        due = forced or due_slots(
            now, config.active_platforms(), jitter_minutes=config.jitter_minutes
        )

        # Off-calendar timely insert (TRENDS.md §6). Only when nothing is
        # already due for that platform this hour — a trend should never
        # displace a scheduled post, only fill a gap.
        timely = None
        if config.trends_enabled and not forced:
            timely = _timely_slot(config, now, {s.platform for s in due})
            if timely:
                due = [*due, timely]

        history = repetition.recent_posts(config, config.repetition_lookback)

        log_event(
            log, "preflight.done",
            projects=len(snapshot.projects), testimonials=len(snapshot.testimonials),
            due=len(due), history=len(history),
        )
        return {
            "now_iso": now.isoformat(),
            "facts_block": snapshot.to_prompt_block(include_testimonials=True),
            "history": history,
            "due": due,
            "counters": {**counters, "due": len(due)},
        }

    return preflight


def _timely_context(config, slot) -> tuple[dict | None, list, str]:
    """`(angle, sources, extra_brief)` for a timely slot; empties otherwise.

    Fetched here rather than passed through graph state because the sources
    carry several KB of extracted text each — putting them in state would mean
    the checkpointer serialising them into Postgres on every step of every run.
    """
    if slot.pillar != "timely":
        return None, [], ""

    from prompts.library import SERVICE_NOTE_NONE, SERVICE_NOTE_SOME, TIMELY_BRIEF
    from trends import angle as angle_mod

    row = angle_mod.ready_angle(config, slot.platform)
    if not row:
        return None, [], ""

    sources = angle_mod.grounding_sources(config, row["trend_id"])
    citation = row.get("citation") or ""
    publisher = citation.split(" - ")[0] if " - " in citation else (citation or "the source")
    url = citation.split(" - ", 1)[1] if " - " in citation else ""
    row = {**row, "citation_url": url}

    service = row.get("service_line") or "none"
    brief = TIMELY_BRIEF.format(
        headline=row["headline"],
        so_what=row["so_what"],
        action=row.get("action") or "(nothing specific)",
        publisher=publisher,
        service_note=(
            SERVICE_NOTE_NONE if service == "none"
            else SERVICE_NOTE_SOME.format(service_line=service)
        ),
    )
    return row, sources, "\n\n" + brief


def make_write(config, budget, reader: SiteReader):
    """Draft each due slot, then re-draft anything the validators reject.

    The regeneration loop is what makes an automated gate usable. Rejecting a
    draft and giving up would mean a missed slot every time the model reached
    for a banned word; feeding the reasons back fixes most of them on the second
    attempt, and a slot that still fails twice is genuinely worth reporting.
    """

    def write(state):
        snapshot = build_snapshot(reader)   # from the reader's cache, not the network
        facts = state.get("facts_block") or ""
        history = state.get("history") or []
        client = LLMClient(
            model=config.voice_model,
            on_usage=budget.on_llm_usage() if budget else None,
        )

        drafts: list[Draft] = []
        rejected: list[dict] = []

        for slot in state.get("due") or []:
            note = ""
            accepted = None
            reasons: list[str] = []

            # A timely slot carries a verified angle plus the captured sources
            # that substantiate it. Those sources are what let the grounding
            # gate accept an external figure at all — without them every
            # timely post is rejected, correctly.
            angle_row, angle_sources, extra_brief = _timely_context(config, slot)
            if slot.pillar == "timely" and not angle_row:
                # The angle expired or was taken between preflight and here.
                # Skipping is right: a timely post with no verified angle would
                # be an ungrounded opinion about the news.
                rejected.append({"platform": slot.platform, "pillar": slot.pillar,
                                 "reasons": ["no ready angle at write time"]})
                continue

            for attempt in range(1, config.max_regenerations + 2):
                if budget and not budget.afford("claude_proxy", 1):
                    reasons = ["daily LLM budget reached"]
                    break
                try:
                    raw = client.complete(
                        system=post_system_prompt(facts),
                        user=post_user_prompt(
                            slot.pillar, slot.platform, slot.fmt, slot.slides,
                            extra_brief + note,
                        ),
                        max_tokens=2000,
                        temperature=0.85,   # copy, not classification
                    )
                except Exception as e:
                    reasons = [f"generation failed: {e}"]
                    break

                parsed = extract_json(raw)
                if not isinstance(parsed, dict):
                    reasons = ["model did not return a JSON object"]
                    note = REGENERATE_NOTE.format(reasons="Return only the JSON object.")
                    continue

                caption = str(parsed.get("caption") or "").strip()
                hashtags = [str(h) for h in (parsed.get("hashtags") or []) if str(h).strip()]
                slides = parsed.get("slides") or []
                slides_text = " ".join(_slide_text(s) for s in slides)
                # Must match what the render node will actually produce, or the
                # platform gate validates a picture that never gets made. Threads
                # is text-first, and the hand-written channels carry whatever the
                # human attaches.
                image_count = (
                    len(slides) if slot.fmt == "carousel"
                    else 0 if slot.platform in ("threads", "x", "youtube")
                    else 1
                )

                verdict = validate(
                    sources=angle_sources,
                    caption=caption,
                    hashtags=hashtags,
                    image_count=image_count,
                    platform_name=slot.platform,
                    snapshot=snapshot,
                    history=history,
                    slides_text=slides_text,
                    repetition_threshold=config.repetition_threshold,
                )
                if verdict.ok:
                    accepted = Draft(
                        platform=slot.platform,
                        pillar=slot.pillar,
                        caption=caption,
                        hashtags=hashtags,
                        slides=slides,
                        title=str(parsed.get("title") or "")[:100],
                        # The citation URL rides on the draft rather than in the
                        # caption. LinkedIn suppresses reach for a link in the
                        # body, so it is posted as a first comment instead —
                        # credible and reach-safe, rather than one or the other.
                        link=(angle_row or {}).get("citation_url", ""),
                        raw={
                            "slot": slot.key,
                            "attempt": attempt,
                            **({"angle_id": angle_row["id"]} if angle_row else {}),
                        },
                    )
                    break

                reasons = verdict.reasons
                log.info(
                    "draft rejected (%s/%s attempt %d): %s",
                    slot.platform, slot.pillar, attempt, verdict.summary(),
                )
                note = REGENERATE_NOTE.format(reasons="\n".join(f"- {r}" for r in reasons))

            if accepted:
                drafts.append(accepted)
                # Guard against two slots in the same run producing near-identical
                # copy — the history table cannot see this run yet.
                history = [*history, accepted.caption]
            else:
                rejected.append(
                    {"platform": slot.platform, "pillar": slot.pillar, "reasons": reasons}
                )

        log_event(log, "write.done", drafted=len(drafts), rejected=len(rejected))
        counters = dict(state.get("counters") or {})
        counters.update({"drafted": len(drafts), "rejected": len(rejected)})
        return {"drafts": drafts, "rejected": rejected, "counters": counters}

    return write


def _slide_text(slide: dict) -> str:
    parts = [str(slide.get(k) or "") for k in ("kicker", "title", "body", "value", "label")]
    for step in slide.get("steps") or []:
        parts += [str(step.get("title") or ""), str(step.get("detail") or "")]
    return " ".join(p for p in parts if p)


def make_render(config):
    """Render slides and host them, because Meta fetches images by URL."""

    def render_node(state):
        drafts = state.get("drafts") or []
        run_id = state.get("run_id") or "run"
        out: list[Draft] = []
        # Accumulated and RETURNED, never appended to `state` in place: LangGraph
        # builds the next state from what a node returns, so a mutation of the
        # dict it was handed is silently discarded.
        rejected = list(state.get("rejected") or [])

        for draft in drafts:
            platform = get_platform(draft.platform, config)
            if not platform.needs_hosted_images:
                out.append(draft)
                continue
            slides = draft.slides or [_fallback_slide(draft)]
            try:
                with tempfile.TemporaryDirectory():
                    paths = render.render_slides(
                        slides, draft.platform, f"{draft.platform}_{draft.pillar}"
                    )
                if config.dry_run:
                    # Render for real, host nothing. The images exist on disk to
                    # be looked at, which is the point of a dry run.
                    draft.image_urls = [f"file://{p}" for p in paths]
                    draft.raw["local_images"] = [str(p) for p in paths]
                else:
                    urls = r2.upload(config, paths, run_id)
                    if urls and not r2.verify_public(urls[0]):
                        raise r2.R2Error(
                            f"{urls[0]} is not publicly readable - Meta would fail to fetch it"
                        )
                    draft.image_urls = urls
                out.append(draft)
            except Exception as e:
                log.error("render/upload failed for %s: %s", draft.platform, e)
                rejected.append(
                    {"platform": draft.platform, "pillar": draft.pillar,
                     "reasons": [f"imaging: {e}"]}
                )

        # Count only what THIS node failed. `rejected` also carries the write
        # node's validator rejections, and reporting those as imaging failures
        # sent someone looking at Chromium for a problem that was a long caption.
        imaging_failed = len(rejected) - len(state.get("rejected") or [])
        log_event(log, "render.done", ready=len(out), imaging_failed=imaging_failed)
        return {"drafts": out, "rejected": rejected}

    return render_node


def _fallback_slide(draft: Draft) -> dict:
    """A single-image post still needs one slide to render."""
    first = draft.caption.split("\n", 1)[0][:90]
    return {
        "role": "statement",
        "theme": "dark" if draft.pillar in ("direct_offer", "proof") else "light",
        "kicker": draft.pillar.replace("_", " ").title(),
        "title": first,
        "body": draft.caption[len(first):].strip()[:180],
    }


def make_publish(config):
    """Publish each draft under an idempotency claim.

    The claim is taken BEFORE the API call and its outcome recorded after. A
    retry after a timeout finds the claim and refuses — which is what stands
    between "the network blipped" and three identical posts on a public page
    that cannot be un-posted.
    """

    def publish(state):
        results = []
        now = datetime.fromisoformat(state["now_iso"])

        for draft in state.get("drafts") or []:
            slot_parts = (draft.platform, draft.pillar, now.date().isoformat())
            key = make_key(AGENT_NAME, f"publish_{draft.platform}", *slot_parts)
            # Hand-written channels record the same key in content.manual_queue,
            # so one slot produces one queue row however many times a run retries.
            draft.raw["idempotency_key"] = key

            with claim(
                key,
                agent=AGENT_NAME,
                kind=f"publish_{draft.platform}",
                target=draft.platform,
                dry_run=config.dry_run,
                url=config.database_url,
            ) as c:
                if not c.granted:
                    log.info("skipping %s: %s", draft.platform, c.reason)
                    results.append(PublishResult.skip(draft.platform, c.reason))
                    continue

                if config.dry_run:
                    log.info("DRY_RUN: would publish to %s", draft.platform)
                    c.succeeded(dry_run=True)
                    results.append(
                        PublishResult(
                            platform=draft.platform, ok=True, external_id="dry-run"
                        )
                    )
                    continue

                result = get_platform(draft.platform, config).publish(draft)
                if result.ok:
                    c.succeeded(external_id=result.external_id, permalink=result.permalink)
                    _mark_angle_used(config, draft)
                else:
                    c.failed(error=result.error)
                results.append(result)
                _record(config, state, draft, result)

        published = sum(1 for r in results if r.ok and not r.skipped)
        counters = dict(state.get("counters") or {})
        counters.update({
            "published": published,
            "publish_failed": sum(1 for r in results if not r.ok),
        })
        log_event(log, "publish.done", **counters)
        return {"results": results, "counters": counters}

    return publish


def _mark_angle_used(config, draft: Draft) -> None:
    """Retire the angle and spend today's insert budget for this platform.

    Only after a successful publish. Marking it earlier would burn the angle on
    a post that failed, and burn the day's one insert with it.
    """
    angle_id = draft.raw.get("angle_id")
    if not angle_id:
        return
    from trends import angle as angle_mod

    angle_mod.mark_used(config, angle_id, draft.platform)


def _record(config, state, draft: Draft, result) -> None:
    """Write the local record. Never fails the publish that already happened."""
    try:
        with connect(config.database_url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO content.social_posts "
                "(run_id, content_type, platform, external_post_id, permalink, status, "
                " error, caption, pillar, image_urls) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
                (
                    state.get("run_id"),
                    draft.raw.get("slot", draft.pillar),
                    draft.platform,
                    result.external_id or None,
                    result.permalink or None,
                    "published" if result.ok else "failed",
                    result.error or None,
                    draft.caption,
                    draft.pillar,
                    json.dumps(draft.image_urls),
                ),
            )
    except Exception:
        log.warning("could not record social_post row", exc_info=True)


def make_notify(config):
    def notify(state):
        results = state.get("results") or []
        rejected = state.get("rejected") or []
        drafts = {d.platform: d for d in (state.get("drafts") or [])}

        if not results and not rejected:
            log.info("nothing due; staying silent")
            return {"counters": state.get("counters") or {}}

        lines = ["📣 <b>Content Poster</b>"]
        for r in results:
            if r.skipped:
                lines.append(f"  ⏭ {esc(r.platform)} - {esc(r.error)}")
            elif r.ok:
                link = f' <a href="{esc(r.permalink)}">link</a>' if r.permalink else ""
                lines.append(f"  ✅ {esc(r.platform)}{link}")
            else:
                lines.append(f"  ❌ {esc(r.platform)}: {esc(r.error[:200])}")
        for item in rejected:
            lines.append(
                f"  🚫 {esc(item['platform'])} ({esc(item['pillar'])}) rejected by validators"
            )
            for reason in item["reasons"][:3]:
                lines.append(f"      {esc(reason[:150])}")

        send("\n".join(lines), topic="content", dry_run=config.dry_run)

        # Preview what actually went out, so it can be judged rather than trusted.
        for platform, draft in drafts.items():
            hosted = [u for u in draft.image_urls if u.startswith("http")]
            caption = f"<b>{esc(platform)}</b>\n{esc(draft.caption[:900])}"
            if len(hosted) > 1:
                send_album(hosted, caption, topic="content", dry_run=config.dry_run)
            elif hosted:
                send_photo(hosted[0], caption, topic="content", dry_run=config.dry_run)
            else:
                send(caption, topic="content", dry_run=config.dry_run, silent=True)

        return {"counters": state.get("counters") or {}}

    return notify
