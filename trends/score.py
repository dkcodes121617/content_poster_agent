"""The relevance gate — where most trends get rejected, on purpose.

This is where pipelines like this usually fail. Not from lack of input, but
from posting about everything, because the pipeline was built to produce output
and producing nothing feels like failure. **Rejecting is the normal outcome.**

Three questions, all of which must pass (TRENDS.md §4):

  1. Is it true and provable?    -> verification step, not here
  2. Does a FOUNDER care?        -> here. Not "is it interesting to developers".
  3. Can we say something true?  -> here, and the weakest of the three.

A Rust compiler improvement fails (2). "The AI tool your competitors started
using does X" passes. The audience is a person running a dental practice or a
fifteen-person SaaS, not the Hacker News front page.

## Groq, not the proxy

Same reasoning as the Lead Finder's classifier: high volume, low stakes, output
is a number and a sentence. Scoring a hundred headlines a day through the Claude
proxy would starve the one job where wording decides the outcome — the angle
synthesis — of its budget.

## Velocity is a multiplier, not a score

A story in one source is noise. The same story in four sources within a day is a
trend. Cross-source corroboration is both the safety mechanism and the ranking
signal, which is one mechanism doing two jobs.
"""
from __future__ import annotations

import json
import logging

from wizcore.llm.client import extract_json

from trends import safety, store

log = logging.getLogger("content_poster.trends.score")

SCORE_SYSTEM = """\
You triage news and discussion for WizCodes, a small software studio in \
Ahmedabad that builds web applications, mobile apps and AI automation for \
businesses in the US, UK and EU. Typical clients run a dental practice, a law \
firm, a restaurant group, or a fifteen-person SaaS company.

For each item, judge whether it is worth that studio posting about on social \
media THIS WEEK.

Score 0-100 on one question: would a non-technical business owner find this \
useful, surprising or worth acting on?

  80-100  changes what a business owner should do right now
  60-79   genuinely useful to know; they would thank you for it
  40-59   mildly interesting, no action implied
  20-39   interesting to engineers only
  0-19    irrelevant, or industry noise

Score LOW, even when the item is objectively important, if it is:
  - a framework, compiler, language or library release
  - infrastructure, DevOps, or anything about how software is built
  - funding rounds, valuations, acquisitions, stock moves
  - developer-culture discussion or opinion pieces about programming
  - anything a business owner would need a developer to explain before caring

Score HIGH when it is:
  - an AI or automation tool a small business could actually use
  - a change in what customers now expect from a website or app
  - a cost, pricing or platform-fee change that hits small businesses
  - a security or compliance change owners must respond to
  - evidence about what does or does not work in software projects

Also decide which WizCodes service line it relates to, if any. "none" is the \
correct and COMMON answer - most useful items do not connect to a service, and \
saying so is better than stretching.

Answer with a JSON array, one object per item, in the same order:
{"i": 0, "score": 72, "service_line": "AI Automation", "audience": "founder", \
"why": "one short sentence a human can check"}

service_line is exactly one of: "Web Development", "Mobile Apps", \
"AI Automation", "none".

Return the array alone, with nothing before or after it."""


def _complete(config, system: str, user: str) -> str:
    """Route scoring to whichever LLM provider is configured.

    `LLM_PROVIDER=proxy` sends everything through the Claude proxy, which is the
    configured default: one credential, one vendor, one place the quirks live.

    The trade is real and worth stating rather than discovering. Measured on
    this workload: the proxy answers a batch in 30-70s against Groq's ~4s, it is
    rate-limited, and it has intermittent 502 spells. Scoring is the highest-
    volume LLM job in the system, so on the proxy it is also the slowest — which
    is survivable precisely because it runs twice a day on a cron and nothing
    waits for it. `LLM_PROVIDER=mixed` restores Groq for triage if that ever
    stops being true.
    """
    if config.llm_provider == "mixed" and config.groq_api_key:
        from groq import Groq

        resp = Groq(api_key=config.groq_api_key).chat.completions.create(
            model=config.groq_classify_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.1,
            max_tokens=4000,
        )
        return resp.choices[0].message.content or ""

    from wizcore.llm.client import LLMClient

    return LLMClient(model=config.classify_model).complete(
        system=system, user=user, max_tokens=4000, temperature=0.1,
    )


def score_batch(config, items: list[dict], budget=None) -> dict[int, dict]:
    """Score items via Groq. Returns `{item_id: verdict}`. Never raises."""
    if not items:
        return {}
    if budget and not budget.afford("groq", 1):
        log.warning("groq budget spent; skipping trend scoring this run")
        return {}

    listing = []
    for index, item in enumerate(items):
        listing.append(
            f"--- item {index} (from {item['source']}) ---\n"
            f"title: {item['title']}\n"
            + (f"summary: {(item.get('summary') or '')[:400]}\n" if item.get("summary") else "")
        )
    prompt = (
        f"Triage these {len(items)} items.\n\n" + "\n".join(listing)
    )

    try:
        raw = _complete(config, SCORE_SYSTEM, prompt)
    except Exception as e:
        log.error("trend scoring failed: %s", e)
        return {}

    parsed = extract_json(raw)
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        log.warning("scorer did not return an array")
        return {}

    out: dict[int, dict] = {}
    for position, entry in enumerate(parsed):
        if not isinstance(entry, dict):
            continue
        index = entry.get("i")
        if not isinstance(index, int) or not 0 <= index < len(items):
            index = position
        if index >= len(items):
            continue
        service = str(entry.get("service_line") or "none")
        if service not in ("Web Development", "Mobile Apps", "AI Automation", "none"):
            service = "none"
        try:
            score = max(0, min(100, int(float(entry.get("score", 0)))))
        except (TypeError, ValueError):
            score = 0
        out[items[index]["id"]] = {
            "score": score,
            "service_line": service,
            "why": str(entry.get("why") or "")[:300],
        }
    return out


def run(config, budget=None) -> dict:
    """Score everything new, apply velocity and the gates, mark the rest rejected."""
    counters = {
        "scored": 0, "passed": 0, "rejected_relevance": 0,
        "rejected_safety": 0, "rejected_seen": 0, "rejected_dupe": 0,
    }
    items = store.unscored(config, limit=config.trend_score_batch)
    if not items:
        return counters

    keys = [i["cluster_key"] for i in items if i.get("cluster_key")]
    velocity = store.cluster_sizes(config, keys)
    covered = store.already_covered(config, keys)

    # ── the free gates first: safety and novelty cost nothing, so they run
    # before the LLM rather than after it. Scoring an item we would refuse to
    # publish anyway is budget spent on a foregone conclusion.
    candidates: list[dict] = []
    seen_clusters: set[str] = set()
    for item in items:
        reason = safety.check_item(
            item["title"], item.get("summary") or "",
            item.get("published_at"), config.trend_cool_off_hours,
        )
        if reason:
            store.mark(config, item["id"], "rejected", 0, reason)
            counters["rejected_safety"] += 1
            continue

        key = item.get("cluster_key") or ""
        if key and key in covered:
            store.mark(config, item["id"], "rejected", 0, "already posted about this story")
            counters["rejected_seen"] += 1
            continue
        if key and key in seen_clusters:
            # Same story, second source, this run. Keep one and drop the rest —
            # they are evidence of velocity, already counted, not new subjects.
            store.mark(config, item["id"], "rejected", 0, "duplicate of another item this run")
            counters["rejected_dupe"] += 1
            continue
        if key:
            seen_clusters.add(key)
        candidates.append(item)

    if not candidates:
        return counters

    verdicts = score_batch(config, candidates, budget)
    counters["scored"] = len(verdicts)

    for item in candidates:
        verdict = verdicts.get(item["id"])
        if not verdict:
            continue
        key = item.get("cluster_key") or ""
        sources_carrying = velocity.get(key, 1)
        # Velocity multiplier, capped. Four independent sources is a strong
        # signal; twelve is the same story syndicated and should not outrank
        # relevance.
        boost = min(config.trend_velocity_cap, sources_carrying - 1) * config.trend_velocity_weight
        final = min(100, verdict["score"] + boost)

        if final < config.trend_min_relevance:
            store.mark(
                config, item["id"], "rejected", final,
                f"relevance {final} < {config.trend_min_relevance}: {verdict['why']}",
            )
            counters["rejected_relevance"] += 1
            continue

        store.mark(config, item["id"], "scored", final, verdict["why"])
        _stash_verdict(config, item["id"], verdict, sources_carrying)
        counters["passed"] += 1

    log.info("trend scoring: %s", counters)
    return counters


def _stash_verdict(config, item_id: int, verdict: dict, sources_carrying: int) -> None:
    """Keep the scorer's reasoning on the row, for the angle step and the digest."""
    from wizcore.db.conn import connect

    try:
        with connect(config.database_url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE content.trend_items "
                "SET raw = raw || %s::jsonb WHERE id = %s",
                (
                    json.dumps({
                        "service_line": verdict["service_line"],
                        "why": verdict["why"],
                        "sources_carrying": sources_carrying,
                    }),
                    item_id,
                ),
            )
    except Exception:
        log.debug("could not stash verdict for %s", item_id, exc_info=True)


def scored_items(config, limit: int = 8) -> list[dict]:
    """Highest-scoring items awaiting verification."""
    from wizcore.db.conn import connect, fetch_all

    try:
        with connect(config.database_url, autocommit=True) as conn:
            return fetch_all(
                conn,
                "SELECT id, source, title, url, summary, relevance, raw, published_at "
                "FROM content.trend_items WHERE status = 'scored' "
                "ORDER BY relevance DESC, surfaced_at DESC LIMIT %s",
                (limit,),
            )
    except Exception:
        return []
