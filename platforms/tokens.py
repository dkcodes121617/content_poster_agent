"""Automatic token rotation. Nobody re-authorises anything by hand.

Three tokens expire in this system and all three are refreshable indefinitely:

| Token | Lifetime | Refresh endpoint |
|---|---|---|
| Instagram | 60d | `graph.instagram.com/refresh_access_token` |
| Threads | 60d | `graph.threads.net/refresh_access_token` |
| Pinterest | 30d access, 60d refresh | `api.pinterest.com/v5/oauth/token` |

Meta's Page token never expires (`debug_token` reports `expires_at = 0`), so it
is checked for validity rather than refreshed — "permanent" is a property of the
token, not a promise about the account, and a revoked app invalidates it
silently.

## The bug this file exists to fix

Refreshing was already happening for Instagram. It achieved nothing, because a
Modal container cannot write its own secret: the new token existed for the
lifetime of the container and was then discarded. Rotated values now go to
`core.agent_credentials` (see `wizcore.db.credentials`), which every agent reads
before falling back to the environment.

**Threads was not being refreshed at all.** It expires 4 Oct 2026 and publishing
would simply have stopped that morning with no error anywhere.

## Refresh early, not late

Every refresh runs weekly regardless of remaining lifetime rather than waiting
for a threshold. A 60-day token refreshed weekly has eight chances to recover
from a transient failure before it expires; one refreshed at day 55 has one.
"""
from __future__ import annotations

import base64
import logging
from datetime import UTC, datetime, timedelta

import requests
from wizcore.db import credentials

log = logging.getLogger("content_poster.tokens")

AGENT = "content_poster"


def _ok(name: str, value: str, expires_in: int, config, note: str = "") -> dict:
    expires_at = (
        datetime.now(UTC) + timedelta(seconds=expires_in) if expires_in else None
    )
    stored = credentials.put(
        name, value, AGENT, expires_at, config.database_url, note
    )
    return {
        "name": name, "ok": True, "stored": stored,
        "expires_in_days": expires_in // 86400 if expires_in else None,
    }


def _fail(name: str, error: str, config) -> dict:
    credentials.record_failure(name, error, AGENT, config.database_url)
    log.warning("rotation failed for %s: %s", name, error[:200])
    return {"name": name, "ok": False, "error": error[:200]}


def refresh_instagram(config) -> dict:
    """Instagram Login token: 60 days, refreshable indefinitely."""
    token = credentials.get("INSTAGRAM_APP_ACCESS_TOKEN", config.database_url) or config.instagram_token
    if not token:
        return {"name": "INSTAGRAM_APP_ACCESS_TOKEN", "ok": False, "error": "not set"}
    try:
        resp = requests.get(
            "https://graph.instagram.com/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": token},
            timeout=30,
        )
        if resp.status_code != 200:
            return _fail("INSTAGRAM_APP_ACCESS_TOKEN", f"HTTP {resp.status_code} {resp.text[:150]}", config)
        payload = resp.json()
        return _ok(
            "INSTAGRAM_APP_ACCESS_TOKEN", payload.get("access_token", ""),
            int(payload.get("expires_in") or 0), config, "60d, refreshable indefinitely",
        )
    except Exception as e:
        return _fail("INSTAGRAM_APP_ACCESS_TOKEN", repr(e), config)


def refresh_threads(config) -> dict:
    """Threads token: 60 days, refreshable indefinitely.

    Nothing refreshed this before. It expires 4 Oct 2026, and publishing would
    have stopped that morning with no error raised anywhere — the silent-failure
    class this whole watchdog exists for.

    The token must be at least 24 hours old before Threads will refresh it, so a
    "cannot refresh" response on a freshly-issued token is expected rather than
    a fault.
    """
    token = credentials.get("THREADS_ACCESS_TOKEN", config.database_url) or config.threads_token
    if not token:
        return {"name": "THREADS_ACCESS_TOKEN", "ok": False, "error": "not set"}
    try:
        resp = requests.get(
            "https://graph.threads.net/refresh_access_token",
            params={"grant_type": "th_refresh_token", "access_token": token},
            timeout=30,
        )
        if resp.status_code != 200:
            return _fail("THREADS_ACCESS_TOKEN", f"HTTP {resp.status_code} {resp.text[:150]}", config)
        payload = resp.json()
        return _ok(
            "THREADS_ACCESS_TOKEN", payload.get("access_token", ""),
            int(payload.get("expires_in") or 0), config, "60d, refreshable indefinitely",
        )
    except Exception as e:
        return _fail("THREADS_ACCESS_TOKEN", repr(e), config)


def refresh_pinterest(config) -> dict:
    """Pinterest: 30-day access token from a 60-day continuous refresh token.

    The refresh token is rotated by Pinterest on some responses and omitted on
    others. Only what actually came back is written — storing an absent refresh
    token would blank a working credential.
    """
    refresh_token = (
        credentials.get("PINTEREST_REFRESH_TOKEN", config.database_url)
        or config.pinterest_refresh_token
    )
    if not (refresh_token and config.pinterest_app_id and config.pinterest_app_secret):
        return {
            "name": "PINTEREST_TOKEN", "ok": False,
            "error": "no refresh token; run tools/pinterest_auth.py once",
        }
    basic = base64.b64encode(
        f"{config.pinterest_app_id}:{config.pinterest_app_secret}".encode()
    ).decode()
    try:
        resp = requests.post(
            "https://api.pinterest.com/v5/oauth/token",
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            return _fail("PINTEREST_TOKEN", f"HTTP {resp.status_code} {resp.text[:150]}", config)
        payload = resp.json()
        result = _ok(
            "PINTEREST_TOKEN", payload.get("access_token", ""),
            int(payload.get("expires_in") or 0), config, "30d access token",
        )
        if payload.get("refresh_token"):
            credentials.put(
                "PINTEREST_REFRESH_TOKEN", payload["refresh_token"], AGENT,
                datetime.now(UTC)
                + timedelta(seconds=int(payload.get("refresh_token_expires_in") or 0) or 5184000),
                config.database_url, "60d, refreshable indefinitely",
            )
            result["refresh_token_rotated"] = True
        return result
    except Exception as e:
        return _fail("PINTEREST_TOKEN", repr(e), config)


def check_meta(config) -> dict:
    """Meta Page token: never expires, but can be revoked without warning.

    Checked rather than refreshed. `expires_at = 0` is a property of the token,
    not a guarantee about the account — revoking the app, a password change or a
    scope change all invalidate it, and publishing then stops silently.
    """
    name = "META_PAGE_ACCESS_TOKEN"
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
            return _fail(name, "debug_token says the token is not valid", config)
        expires = int(data.get("expires_at") or 0)
        return {
            "name": name, "ok": True, "stored": False,
            "expires_in_days": None if not expires else
            int((datetime.fromtimestamp(expires, tz=UTC) - datetime.now(UTC)).days),
        }
    except Exception as e:
        return _fail(name, repr(e), config)


def refresh_all(config) -> dict:
    """Rotate every rotatable token and check the rest. Never raises.

    Only touches platforms that are actually enabled — a disabled platform's
    stale credential should not generate a weekly alert nobody can act on.
    """
    enabled = set(config.active_platforms())
    results = []
    if "instagram" in enabled:
        results.append(refresh_instagram(config))
    if "threads" in enabled:
        results.append(refresh_threads(config))
    if "pinterest" in enabled:
        results.append(refresh_pinterest(config))
    if "facebook" in enabled:
        results.append(check_meta(config))

    failed = [r for r in results if not r.get("ok")]
    return {
        "checked": len(results),
        "rotated": sum(1 for r in results if r.get("stored")),
        "failed": len(failed),
        "results": results,
    }


def alert_if_needed(config, outcome: dict) -> None:
    """Telegram only when something needs a human. Silence is the healthy case.

    A weekly "all tokens fine" message trains you to ignore the channel, and
    then the one that says otherwise gets ignored too.
    """
    from wizcore.telegram.send import esc, send

    problems = [r for r in outcome.get("results", []) if not r.get("ok")]
    stale = credentials.stale_rotations(45, config.database_url)
    soon = [c for c in credentials.expiring(14, config.database_url) if c.get("expires_at")]

    if not (problems or stale or soon):
        return

    lines = ["🔑 <b>Token rotation needs attention</b>"]
    for r in problems:
        lines.append(f"  ❌ {esc(r['name'])}: {esc(str(r.get('error', ''))[:140])}")
    for c in soon:
        lines.append(
            f"  ⏳ {esc(c['name'])} expires {c['expires_at']:%d %b}"
            f" (rotated {c['rotations']}x)"
        )
    for c in stale:
        # The quiet failure: no error, no exception, simply never ran.
        lines.append(
            f"  ⚠️ {esc(c['name'])} has not rotated since {c['rotated_at']:%d %b}"
        )
    send("\n".join(lines), topic="alerts")
