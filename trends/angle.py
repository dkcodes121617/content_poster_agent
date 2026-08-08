"""Turning a verified trend into something worth a founder's attention.

The hard creative step, and the one worth spending the good model on. The
structure (TRENDS.md §5):

    1. the news, cited            "X shipped Y this week."
    2. the second-order effect    "Which means Z is now trivial / newly broken."
    3. what an owner should DO    "If you run a booking flow, check ..."
    4. how we relate  (optional)  "We rebuilt exactly this for <real project>."

**Step 4 is absent from most angles and that is the design, not a shortfall.**
`service_line = 'none'` is the expected value roughly four times in five. An
account that ties every trend back to its own services is doing native
advertising and everybody can tell; the one post in five that does connect is
credible precisely because the other four did not.

## Every claim carries its source

The angle stores `claims` — each figure paired with the URL that substantiates
it. That is what `wizcore.facts.grounding` reads to let an external number
through, and what the citation line renders from. A claim with no source does
not get written down, so it cannot later be published by accident.
"""
from __future__ import annotations

import json
import logging

from wizcore.facts import grounding
from wizcore.llm.client import LLMClient, extract_json

from trends import safety, store

log = logging.getLogger("content_poster.trends.angle")

ANGLE_SYSTEM = """\
You turn a piece of news into something a business owner can use.

The audience is not developers. It is someone running a dental practice, a law \
firm, a restaurant group or a small SaaS company. They are smart, busy, and do \
not care about software for its own sake.

Produce four things:

  headline  - the CONSEQUENCE, not the announcement. Not "OpenAI released X" \
but "Your competitor's support queue got cheaper on Tuesday." One sentence.
  so_what   - the second-order effect. What is now possible, trivial, broken or \
no longer a competitive advantage. Two sentences at most.
  action    - what a business owner should actually check or do this week. \
Concrete and small enough to act on. One sentence. Use "" if there is honestly \
nothing to do.
  service_line - which WizCodes service this genuinely relates to, or "none".

On service_line: "none" is the RIGHT answer most of the time and there is no \
penalty for it. Only name a service when a business owner acting on this would \
plausibly need that kind of work. Never stretch - a forced connection is \
obvious to a reader and costs more trust than the mention gains.

Rules that are checked automatically after you write:
  - Every number you state must appear in the source extracts provided. If a \
figure is not in them, leave it out entirely rather than approximating.
  - Criticise practices, never companies or people. "Per-seat pricing for AI \
tools will age badly" is fine. "Vendor X is greedy" is not.
  - No buzzwords: leverage, seamless, unlock, elevate, game-changer, \
cutting-edge, empower, revolutionise.
  - Do not mention WizCodes. That connection is made later, by a different step.

Answer with a JSON object:
{"headline": "...", "so_what": "...", "action": "...", \
"service_line": "AI Automation", "claims": [{"claim": "...", "source_url": "..."}], \
"good_for": ["threads","linkedin","blog"]}

good_for lists where this genuinely fits: "threads" for a sharp one-liner, \
"linkedin" for something a founder would repost, "x" for a thread, "blog" when \
it deserves 800 words and would rank. Include only what fits.

Return the object alone, with nothing before or after it."""


def _user_prompt(item: dict, sources: list[dict]) -> str:
    lines = [
        f"NEWS: {item['title']}",
        f"Where it surfaced: {item['source']}" + (f" - {item['url']}" if item.get("url") else ""),
    ]
    if item.get("summary"):
        lines.append(f"Summary: {item['summary'][:600]}")
    lines += ["", "SOURCE EXTRACTS - the only facts you may state as true:", ""]
    for index, source in enumerate(sources, 1):
        label = source.get("publisher") or source.get("title") or "source"
        lines += [
            f"[{index}] {label} - {source['url']}",
            (source.get("extract") or "")[:1400],
            "",
        ]
    lines.append("Write the angle.")
    return "\n".join(lines)


def synthesise(config, item: dict, sources: list[dict], budget=None) -> dict | None:
    """One angle from one verified trend, or None if it cannot pass the gates."""
    if budget and not budget.afford("claude_proxy", 1):
        log.warning("proxy budget spent; skipping angle synthesis")
        return None

    client = LLMClient(
        model=config.voice_model,
        on_usage=budget.on_llm_usage() if budget else None,
    )
    note = ""
    for attempt in range(1, config.trend_angle_attempts + 1):
        try:
            raw = client.complete(
                system=ANGLE_SYSTEM,
                user=_user_prompt(item, sources) + note,
                max_tokens=900,
                temperature=0.7,
            )
        except Exception as e:
            log.warning("angle synthesis failed for %s: %s", item["id"], e)
            return None

        parsed = extract_json(raw)
        if not isinstance(parsed, dict):
            note = "\n\nReturn only the JSON object."
            continue

        headline = str(parsed.get("headline") or "").strip()
        so_what = str(parsed.get("so_what") or "").strip()
        if not (headline and so_what):
            continue

        problems = _check(config, parsed, sources)
        if not problems:
            parsed["headline"] = headline
            parsed["so_what"] = so_what
            return parsed

        log.info(
            "angle rejected for %s (attempt %d): %s",
            item["id"], attempt, "; ".join(problems),
        )
        note = (
            "\n\nThe previous attempt was rejected:\n"
            + "\n".join(f"- {p}" for p in problems)
            + "\nWrite a fresh version that avoids those problems."
        )
    return None


def _check(config, parsed: dict, sources: list[dict]) -> list[str]:
    """Gates that run before an angle is stored at all.

    Cheaper to fail here than at publish time: a bad angle rejected now costs
    one retry, while one stored and rejected later has already consumed a
    calendar slot.
    """
    text = " ".join(
        str(parsed.get(k) or "") for k in ("headline", "so_what", "action")
    )
    problems = safety.check_draft(text)

    # External figures must appear in the captured extracts. The snapshot is not
    # consulted here - an angle is about the world, and any claim about WizCodes
    # at this stage would be out of scope anyway (the prompt forbids mentioning us).
    corpus = " ".join((s.get("extract") or "") for s in sources).lower()
    for figure in _figures(text):
        digits = "".join(c for c in figure if c.isdigit())
        if digits and digits not in corpus and figure.lower() not in corpus:
            problems.append(
                f"[grounding] figure {figure!r} is in none of the source extracts"
            )

    service = str(parsed.get("service_line") or "none")
    if service not in ("Web Development", "Mobile Apps", "AI Automation", "none"):
        problems.append(f"[schema] service_line {service!r} is not a real service line")
    return problems


def _figures(text: str) -> list[str]:
    import re

    return [
        m.strip() for m in re.findall(
            r"(?<![\w.])(?:[$£€]\s?\d[\d,.]*\s?[kmb]?|\d[\d,.]*\s?%|\d[\d,.]*\s?x\b|\d{4,})",
            text, re.I,
        )
    ]


def run(config, budget=None) -> dict:
    """Synthesise angles for every verified trend."""
    from wizcore.db.conn import connect, fetch_all

    counters = {"angles": 0, "angle_failed": 0}
    try:
        with connect(config.database_url, autocommit=True) as conn:
            items = fetch_all(
                conn,
                "SELECT id, source, title, url, summary, relevance, raw "
                "FROM content.trend_items WHERE status = 'verified' "
                "ORDER BY relevance DESC LIMIT %s",
                (config.trend_angles_per_run,),
            )
    except Exception:
        log.error("could not read verified trends", exc_info=True)
        return counters

    for item in items:
        sources = store.sources_for(config, item["id"])
        if not sources:
            store.mark(config, item["id"], "rejected", item.get("relevance"),
                       "verified but no sources stored")
            counters["angle_failed"] += 1
            continue

        angle = synthesise(config, item, sources, budget)
        if not angle:
            store.mark(config, item["id"], "rejected", item.get("relevance"),
                       "no angle survived the gates")
            counters["angle_failed"] += 1
            continue

        _save(config, item, angle, sources)
        store.mark(config, item["id"], "angled", item.get("relevance"), "")
        counters["angles"] += 1

    log.info("trend angles: %s", counters)
    return counters


def _save(config, item: dict, angle: dict, sources: list[dict]) -> None:
    from wizcore.db.conn import connect

    primary = sources[0]
    citation = f"{primary.get('publisher') or primary.get('title') or 'source'} - {primary['url']}"
    good_for = [p for p in (angle.get("good_for") or []) if isinstance(p, str)]
    try:
        with connect(config.database_url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO content.trend_angles "
                "(trend_id, headline, so_what, action, service_line, claims, "
                " citation, good_for, expires_at) "
                "VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb, "
                "        now() + make_interval(hours => %s))",
                (
                    item["id"],
                    angle["headline"][:500],
                    angle["so_what"][:1000],
                    (angle.get("action") or "")[:500] or None,
                    angle.get("service_line") or "none",
                    json.dumps(angle.get("claims") or []),
                    citation[:500],
                    json.dumps(good_for or ["threads"]),
                    config.trend_angle_ttl_hours,
                ),
            )
    except Exception:
        log.error("could not save angle for trend %s", item["id"], exc_info=True)


def ready_angle(config, platform: str) -> dict | None:
    """The best unused angle that fits `platform`, or None.

    Ordered by relevance then freshness — a strong angle from this morning
    beats a mediocre one from an hour ago, but a stale strong one loses to
    both, which is what `expires_at` enforces.
    """
    from wizcore.db.conn import connect, fetch_one

    try:
        with connect(config.database_url, autocommit=True) as conn:
            return fetch_one(
                conn,
                "SELECT a.*, i.relevance, i.url AS source_url, i.title AS source_title "
                "FROM content.trend_angles a "
                "JOIN content.trend_items i ON i.id = a.trend_id "
                "WHERE a.status = 'ready' AND a.expires_at > now() "
                "  AND (a.good_for @> %s::jsonb OR jsonb_array_length(a.good_for) = 0) "
                "ORDER BY i.relevance DESC NULLS LAST, a.created_at DESC LIMIT 1",
                (json.dumps([platform]),),
            )
    except Exception:
        log.warning("could not read ready angles", exc_info=True)
        return None


def mark_used(config, angle_id: int, platform: str) -> None:
    from wizcore.db.conn import connect

    try:
        with connect(config.database_url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE content.trend_angles SET status = 'used', used_at = now(), "
                "used_platform = %s WHERE id = %s",
                (platform, angle_id),
            )
            cur.execute(
                "INSERT INTO content.trend_inserts (day, platform, angle_id) "
                "VALUES (current_date, %s, %s) ON CONFLICT (day, platform) DO NOTHING",
                (platform, angle_id),
            )
    except Exception:
        log.warning("could not mark angle %s used", angle_id, exc_info=True)


def insert_available(config, platform: str) -> bool:
    """Has the one off-calendar insert for this platform today been spent?

    A table rather than an in-memory counter: the cap is per DAY and the agent
    runs hourly, so a run has no idea what earlier runs did.
    """
    from wizcore.db.conn import connect, fetch_one

    try:
        with connect(config.database_url, autocommit=True) as conn:
            row = fetch_one(
                conn,
                "SELECT 1 AS taken FROM content.trend_inserts "
                "WHERE day = current_date AND platform = %s",
                (platform,),
            )
        return row is None
    except Exception:
        # Unknown means "do not insert". Silence is the safe failure for a
        # feature whose whole risk is posting too often.
        return False


def grounding_sources(config, trend_id: int) -> list[dict]:
    """Captured extracts, shaped for `wizcore.facts.grounding.check`."""
    return store.sources_for(config, trend_id)


__all__ = [
    "grounding",  # re-exported so callers pass the same gate the writer uses
    "grounding_sources",
    "insert_available",
    "mark_used",
    "ready_angle",
    "run",
    "synthesise",
]
