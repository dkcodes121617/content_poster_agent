"""Modal deployment for the Content Poster.

    modal deploy modal_app.py       (or: .\\deploy.ps1)
    modal run modal_app.py::manual --dry-run true

## Hourly cron, calendar inside

Modal's scheduler is UTC and the campaign is written in IST, so rather than
encoding seventeen UTC cron expressions that drift at every DST change on the
audience side, this wakes hourly and asks the calendar what is due. A quiet hour
short-circuits at the first node and costs nothing.

That also makes the jitter possible: a cron cannot fire at 20:07 one day and
19:52 the next, but a calendar consulted hourly can — and a post landing at
exactly 20:00:00 every time is a fingerprint.

## The image is baked in

Fonts are assets, not dependencies. The brand mark is drawn on every single
image, so a run must never fail because Google Fonts was slow.
"""
from __future__ import annotations

from datetime import UTC

import modal

app = modal.App("wizcodes-content")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install_from_requirements("requirements.txt")
    # Chromium for the slide renderer. ~400 MB and a slower cold start, which is
    # the cheapest line in the budget for an agent rendering a few dozen slides
    # a week — and the only way the slides inherit the site's real CSS rather
    # than imitating it with draw calls.
    .run_commands("playwright install --with-deps chromium")
    .add_local_dir("assets", "/root/assets")
    .add_local_dir("templates", "/root/templates")
    .add_local_python_source("wizcore")
    .add_local_python_source(
        "config", "main", "campaign", "graph", "imaging", "platforms", "prompts",
        "validators", "trends",
    )
    # tools/render.py is loaded by path at runtime, so it has to be present as a
    # file rather than as an imported module.
    .add_local_dir("tools", "/root/tools")
)

secret = modal.Secret.from_name("wizcodes-content")


@app.function(
    image=image,
    secrets=[secret],
    # THE only cron in this app. Twice an hour; the calendar decides what is
    # due, and the dispatcher below decides what else runs on this tick.
    schedule=modal.Cron("0,30 * * * *"),
    timeout=1800,                        # rendering + several platform APIs
    max_containers=1,                    # never two publishers at once
    retries=0,                           # idempotency claims handle safe retries
)
def scheduled() -> dict:
    """The only cron in this app. Everything else is dispatched from here.

    ## Why one function instead of six

    Modal's plan allows **5 scheduled functions per workspace** and the three
    agents declared ten between them. Consolidating is the better answer than
    upgrading anyway: six crons meant six cold starts and six containers a day
    doing work that takes seconds, and the sub-tasks below were never
    independent — a trend refine exists to have an angle ready before the
    posting run that reads it.

    ## Twice an hour, not once

    `0,30` rather than `0`. Two things need it. The daily brief has to land at
    exactly 18:30 UTC (00:00 IST), and a calendar slot's 45-minute window with
    ±25 minutes of jitter can open and close between two hourly ticks. Double
    the ticks and no slot can be missed.

    Publishing twice as often is safe because it always was: `core.external_actions`
    claims a slot before the API call, so a second tick that finds the same slot
    due refuses rather than duplicates. That guarantee is what makes this
    schedule a free choice rather than a risk.

    ## Every sub-task is isolated

    One `try` each. A trend harvest failing must never stop the posting run that
    is the point of the agent, and the reverse is equally true.
    """
    from datetime import datetime

    now = datetime.now(UTC)
    hour, minute, weekday = now.hour, now.minute, now.weekday()
    out: dict = {}

    def step(name: str, fn) -> None:
        try:
            result = fn()
            out[name] = result if isinstance(result, (int, str)) else "ok"
        except Exception as e:
            out[name] = f"failed: {type(e).__name__}"
            log_step_failure(name, e)

    # The posting run, every tick. First, so nothing below can delay it.
    from main import run_once

    try:
        out.update(run_once())
    except Exception as e:
        out["run_failed"] = f"{type(e).__name__}: {e}"[:200]

    # Free APIs, no LLM. Cheap enough that missing a trend costs more than
    # running it does — but hourly rather than half-hourly, since nothing
    # downstream reads it faster than that.
    if minute < 30:
        step("harvest", lambda: _trends("harvest"))

    # Ahead of the morning and evening posting windows, so an angle is ready
    # when a slot opens rather than an hour after it closed.
    if (hour, minute) in ((4, 30), (13, 30)):
        step("refine", lambda: _trends("refine"))

    # Event-driven on a poll: the blog agent publishes hourly and has no signal
    # to send, so this asks "is there a post nobody has syndicated?" and usually
    # answers no for free.
    if (hour, minute) in ((6, 30), (16, 30)):
        step("syndicate", _syndicate)

    # 18:30 UTC = 00:00 IST. The Indian day starts, and the calendar's first
    # slot is 11:00 IST — so this is the only hour where the plan arrives
    # before the work does.
    if (hour, minute) == (18, 30):
        step("brief", _daily_brief)

    # Weekly, every token regardless of remaining lifetime. A 60-day token
    # refreshed weekly has eight chances to survive a transient failure.
    if weekday == 0 and (hour, minute) == (4, 0):
        step("tokens", _rotate_tokens)

    return out


def log_step_failure(name: str, exc: BaseException) -> None:
    """A failed sub-task alerts, but never fails the tick.

    Silent is the one thing it must not be: a trend harvest that has been
    throwing for a fortnight looks exactly like a quiet news week.
    """
    import contextlib
    import logging

    from wizcore.telegram.send import alert

    logging.getLogger("content_poster.modal").exception("scheduled step %s failed", name)
    with contextlib.suppress(Exception):
        alert("content_poster", exc, context=f"scheduled step: {name}")



# ── the work, as plain functions ─────────────────────────────────────────────
# `scheduled()` dispatches to these, and the @app.function wrappers below call
# the same code so `modal run` still reaches every task individually. One
# implementation, two entry points — the alternative is a manual trigger that
# quietly does something different from the cron.
def _daily_brief() -> dict:
    import uuid

    from wizcore.obs.log import setup_logging

    from campaign import brief
    from config import AGENT_NAME, CONFIG

    setup_logging(AGENT_NAME, str(uuid.uuid4()), CONFIG.log_level)
    return brief.send_daily(CONFIG)


def _syndicate() -> dict:
    return _syndicate()


def _trends(mode: str) -> dict:
    """`harvest` is free and hourly; `refine` costs money and runs twice a day.

    Split because the stages have different costs. A spike in trend volume
    should cost HTTP requests, not LLM budget, and separating them is what
    guarantees that.
    """
    from config import CONFIG
    from trends import run

    if mode == "harvest":
        return run.harvest_only(CONFIG)

    from wizcore.db.spend import BudgetGuard

    from config import AGENT_NAME

    budget = BudgetGuard.load(AGENT_NAME, CONFIG.budget_caps, CONFIG.database_url)
    try:
        return run.refine(CONFIG, budget)
    finally:
        budget.flush()


def _rotate_tokens() -> dict:
    from config import CONFIG
    from platforms import tokens

    outcome = tokens.refresh_all(CONFIG)
    tokens.alert_if_needed(CONFIG, outcome)
    return outcome


@app.function(
    image=image,
    secrets=[secret],
    # 18:30 UTC = 00:00 IST. Modal crons are UTC, and the whole point of this
    # message is that it lands as the Indian day starts — the calendar's first
    # slot is 11:00 IST, so midnight is the only hour where the plan arrives
    # before the work does.
    timeout=300,
    max_containers=1,
    retries=1,
)
def daily_brief() -> dict:
    """The 00:00 IST brief. Also dispatched from `scheduled()` at 18:30 UTC."""
    return _daily_brief()


@app.function(image=image, secrets=[secret], timeout=1800)
def manual(dry_run: bool = True, force: str = "") -> dict:
    """Ad-hoc run. Defaults to the safe path, because a manual trigger is
    exactly when someone is experimenting."""
    import dataclasses

    from campaign.calendar import Slot, ist_now
    from config import CONFIG
    from main import run_once

    config = dataclasses.replace(CONFIG, dry_run=True) if dry_run else CONFIG
    forced = None
    if force:
        parts = force.split(":")
        now = ist_now(config.display_tz)
        forced = [
            Slot(
                weekday=now.weekday(), hour=now.hour, minute=now.minute,
                platform=parts[0], pillar=parts[1] if len(parts) > 1 else "proof",
                fmt=parts[2] if len(parts) > 2 else "single",
                slides=int(parts[3]) if len(parts) > 3 else 0,
            )
        ]
    return run_once(config, forced=forced)


@app.function(
    image=image,
    secrets=[secret],
    # Twice daily. Event-driven work on a poll: the blog agent publishes hourly
    # and there is no signal it can send, so this asks "is there a post nobody
    # has syndicated?" and usually answers no for free.
    timeout=600,
    max_containers=1,
    retries=0,
)
def syndicate_devto() -> dict:
    """Republish the newest un-syndicated blog post to dev.to.

    Separate from the calendar because it is event-driven: it fires when a post
    exists that has not been syndicated, not at a fixed hour. `promoted_assets`
    keyed (asset_type, slug) is what makes that question answerable and makes a
    double-syndication impossible.
    """
    return _syndicate()


@app.function(
    image=image,
    secrets=[secret],
    # Hourly. Free APIs only, no LLM, no metered vendor — cheap enough that
    # missing a trend costs more than running this does.
    timeout=600,
    max_containers=1,
    retries=1,
)
def trends_harvest() -> dict:
    """Fetch from the free sources into content.trend_items.

    Separate from `refine` because the stages have different costs. A spike in
    trend volume should cost HTTP requests, not LLM budget, and splitting them
    is what guarantees that.
    """
    return _trends("harvest")


@app.function(
    image=image,
    secrets=[secret],
    # Twice daily, ahead of the morning and evening posting windows, so an
    # angle is ready when a slot opens rather than an hour after it closed.
    timeout=1200,
    max_containers=1,
    retries=0,
)
def trends_refine() -> dict:
    """Score, verify and synthesise. The stages that cost money.

    The expensive model only ever sees items that already cleared every free
    gate — safety, novelty, relevance and corroboration — which is why this can
    run twice a day on a free tier.
    """
    return _trends("refine")


@app.function(
    image=image,
    secrets=[secret],
    # Weekly, and every token every week regardless of remaining lifetime. A
    # 60-day token refreshed weekly has eight chances to survive a transient
    # failure; one refreshed at day 55 has one.
    timeout=300,
    retries=1,
)
def rotate_tokens() -> dict:
    """Rotate every expiring token, with nobody re-authorising anything.

    Instagram, Threads and Pinterest all expire and all three are refreshable
    indefinitely, so this should never need a human. It previously did for one
    mechanical reason: a Modal container cannot write its own secret, so a
    refreshed token was discarded when the container exited. Rotated values now
    go to `core.agent_credentials`, which every agent reads before falling back
    to the environment.

    Telegram is only touched when something actually needs attention — a weekly
    "all fine" message is how an alert channel becomes one nobody reads.
    """
    return _rotate_tokens()


@app.function(image=image, secrets=[secret], timeout=300)
def refresh_tokens() -> dict:
    """Weekly: refresh the Instagram token while it is still valid.

    It lasts 60 days and is refreshable indefinitely, but only *before* it
    expires. Publishing that silently stops two months from now is exactly the
    failure this prevents, and it is the reason this is a separate cron rather
    than something the main run does when it happens to notice.

    The recording half matters just as much. Meta and Instagram tokens fail
    silently - nothing errors, publishing simply stops - so
    `core.credential_expiry` is what turns that into a digest line ten days
    ahead instead of a month of nobody noticing.
    """
    from datetime import UTC, datetime, timedelta

    from wizcore.db.conn import connect
    from wizcore.telegram.send import send

    from config import CONFIG
    from platforms.instagram import InstagramPlatform

    results: dict[str, object] = {}
    ok, detail = InstagramPlatform(CONFIG).refresh_if_stale()
    results["instagram_refreshed"] = ok
    expires_at = None
    if ok and str(detail).isdigit():
        expires_at = datetime.now(UTC) + timedelta(seconds=int(detail))
    if not ok:
        send(f"⚠️ Instagram token refresh failed: {detail}", topic="alerts")

    # Pinterest: 30-day access token, 60-day refresh token that is refreshable
    # indefinitely. Refreshing weekly makes it permanent in practice. A rotated
    # access token has to be written back to the secret, which a container
    # cannot do — so it is reported rather than silently lost.
    pin_ok, pin_detail, pin_values = _pinterest_refresh(CONFIG)
    if pin_values.get("PINTEREST_TOKEN"):
        results["pinterest_new_token"] = True
        send(
            "🔄 <b>Pinterest token refreshed.</b> Persist it locally, then "
            "redeploy the secret:\n"
            "<code>cd content_poster_agent</code>\n"
            "<code>python tools/set_env.py PINTEREST_TOKEN=&lt;new&gt;</code>\n"
            "<code>.\\deploy.ps1 -SecretOnly</code>\n"
            "The value is in this run's Modal logs.",
            topic="alerts",
        )
    results["pinterest_refreshed"] = pin_ok
    results["pinterest_detail"] = pin_detail

    checks = [
        ("INSTAGRAM_APP_ACCESS_TOKEN", ok, expires_at),
        ("PINTEREST_TOKEN", pin_ok, None),
        *_meta_check(CONFIG),
    ]
    try:
        with connect(CONFIG.database_url, autocommit=True) as conn, conn.cursor() as cur:
            for name, healthy, expiry in checks:
                cur.execute(
                    "INSERT INTO core.credential_expiry "
                    "(name, agent, expires_at, last_checked, last_ok) "
                    "VALUES (%s, 'content_poster', %s, now(), %s) "
                    "ON CONFLICT (name) DO UPDATE SET "
                    "  expires_at = EXCLUDED.expires_at, last_checked = now(), "
                    "  last_ok = EXCLUDED.last_ok",
                    (name, expiry, healthy),
                )
        results["recorded"] = len(checks)
    except Exception as e:
        results["record_error"] = str(e)[:200]
    return results


def _pinterest_refresh(config) -> tuple[bool, str, dict]:
    """Refresh Pinterest, but only when it is a platform we actually publish to.

    Skipped when Pinterest is not in PLATFORMS_ENABLED, so a disabled platform's
    stale credential does not generate a weekly alert nobody can act on.
    """
    if "pinterest" not in config.active_platforms():
        return True, "pinterest not enabled; skipped", {}
    from platforms.pinterest import PinterestPlatform

    return PinterestPlatform(config).refresh()


def _meta_check(config) -> list[tuple]:
    """Is the Page token still alive, and when does it expire?

    `expires_at = 0` from debug_token means never — a real property of this
    token, but not a guarantee about the account: revoking the app, a password
    change or a scope change all invalidate it without warning.
    """
    from datetime import UTC, datetime

    import requests

    try:
        resp = requests.get(
            f"https://graph.facebook.com/{config.meta_graph_version}/debug_token",
            params={
                "input_token": config.meta_page_token,
                "access_token": f"{config.meta_app_id}|{config.meta_app_secret}",
            },
            timeout=25,
        )
        data = (resp.json().get("data") or {}) if resp.status_code == 200 else {}
        if not data.get("is_valid"):
            return [("META_PAGE_ACCESS_TOKEN", False, None)]
        expires = data.get("expires_at") or 0
        if not expires:
            return [("META_PAGE_ACCESS_TOKEN", True, None)]
        return [("META_PAGE_ACCESS_TOKEN", True, datetime.fromtimestamp(expires, tz=UTC))]
    except Exception:
        return [("META_PAGE_ACCESS_TOKEN", False, None)]


@app.local_entrypoint()
def cli(dry_run: bool = True, force: str = ""):
    print(manual.remote(dry_run=dry_run, force=force))
