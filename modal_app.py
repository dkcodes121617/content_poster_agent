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
    schedule=modal.Cron("0 * * * *"),   # hourly; the calendar decides what is due
    timeout=1800,                        # rendering + several platform APIs
    max_containers=1,                    # never two publishers at once
    retries=0,                           # idempotency claims handle safe retries
)
def scheduled() -> dict:
    from main import run_once

    return run_once()


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
    schedule=modal.Cron("30 6,16 * * *"),
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
    from campaign import syndicate
    from config import CONFIG

    return syndicate.run(CONFIG)


@app.function(
    image=image,
    secrets=[secret],
    # Hourly. Free APIs only, no LLM, no metered vendor — cheap enough that
    # missing a trend costs more than running this does.
    schedule=modal.Cron("15 * * * *"),
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
    from config import CONFIG
    from trends import run

    return run.harvest_only(CONFIG)


@app.function(
    image=image,
    secrets=[secret],
    # Twice daily, ahead of the morning and evening posting windows, so an
    # angle is ready when a slot opens rather than an hour after it closed.
    schedule=modal.Cron("50 4,13 * * *"),
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
    from wizcore.db.spend import BudgetGuard

    from config import AGENT_NAME, CONFIG
    from trends import run

    budget = BudgetGuard.load(AGENT_NAME, CONFIG.budget_caps, CONFIG.database_url)
    try:
        return run.refine(CONFIG, budget)
    finally:
        budget.flush()


@app.function(
    image=image,
    secrets=[secret],
    # Weekly, and every token every week regardless of remaining lifetime. A
    # 60-day token refreshed weekly has eight chances to survive a transient
    # failure; one refreshed at day 55 has one.
    schedule=modal.Cron("0 4 * * 1"),
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
    from config import CONFIG
    from platforms import tokens

    outcome = tokens.refresh_all(CONFIG)
    tokens.alert_if_needed(CONFIG, outcome)
    return outcome


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
