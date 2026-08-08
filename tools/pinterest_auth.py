"""One-time Pinterest OAuth, to replace the 24-hour test token.

    python tools/pinterest_auth.py

## Why this exists

The token originally configured was a **test token generated in the Pinterest
app dashboard**. Those last 24 hours and cannot be refreshed — which is exactly
what happened: it passed preflight one morning and 401'd the same afternoon.

Pinterest offers no permanent token. What it does offer is a **continuous
refresh token**: 60 days, refreshable *indefinitely*. Run this once, and the
weekly `refresh_tokens` cron keeps the access token alive forever without anyone
touching it again — the same arrangement Instagram already has.

## What you need first

In your app at developers.pinterest.com:

  1. App ID and App secret (the "App details" page).
  2. A **Redirect URI** registered on the app. Add exactly:
         http://localhost:8085/callback
     Pinterest matches this string exactly, so a trailing slash matters.
  3. Trial access is enough to create pins on your own account. Standard access
     is only needed to act on behalf of other users, which this agent never does.

The scopes requested below are the minimum for what the agent actually does:
read the account, list boards, and create pins. `boards:write` is included only
so the board this agent needs can be created from here rather than by hand.
"""
from __future__ import annotations

import base64
import http.server
import secrets
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

import requests

AGENT_ROOT = Path(__file__).resolve().parent.parent
REDIRECT_URI = "http://localhost:8085/callback"
SCOPES = "user_accounts:read,boards:read,boards:write,pins:read,pins:write"
_AUTH = "https://www.pinterest.com/oauth/"
_TOKEN = "https://api.pinterest.com/v5/oauth/token"

_received: dict[str, str] = {}


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        _received.update({k: v[0] for k, v in params.items()})
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        body = (
            "<h2>Pinterest authorised.</h2><p>You can close this tab and return "
            "to the terminal.</p>"
            if "code" in _received
            else f"<h2>Authorisation failed.</h2><pre>{_received}</pre>"
        )
        self.wfile.write(body.encode())

    def log_message(self, *args):  # silence the default stderr logging
        return


def _env(key: str) -> str:
    env = AGENT_ROOT / ".env"
    for line in env.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            if name.strip() == key:
                return value.strip()
    return ""


def _ask(prompt: str) -> str:
    """Prompt, but degrade to a clear message when there is no terminal.

    This gets run from automation as often as by hand, and a bare `input()` with
    no stdin raises EOFError — a traceback that says nothing about the actual
    problem, which is one missing configuration value.
    """
    try:
        return input(prompt).strip()
    except (EOFError, OSError):
        return ""


def main() -> int:
    app_id = _env("PINTEREST_APP_ID") or _ask("Pinterest App ID: ")
    app_secret = _env("PINTEREST_APP_SECRET") or _ask("Pinterest App secret: ")
    if not app_id:
        print(
            "\nPINTEREST_APP_ID is not set, and it cannot be derived - Pinterest\n"
            "exposes no token-introspection endpoint, so the App ID has to come\n"
            "from the console.\n\n"
            "  1. https://developers.pinterest.com/apps/\n"
            "  2. Open your app. The App ID sits directly above the App secret key\n"
            "     you already have - a numeric value, no 'pina_' prefix.\n"
            "  3. python tools/set_env.py PINTEREST_APP_ID=<that number>\n"
            "  4. python tools/pinterest_auth.py\n\n"
            "While you are on that page, add this exact Redirect URI to the app:\n"
            f"  {REDIRECT_URI}\n"
            "Pinterest matches it as an exact string, so a trailing slash breaks it.\n",
            file=sys.stderr,
        )
        return 2
    if not app_secret:
        print("PINTEREST_APP_SECRET is not set.", file=sys.stderr)
        return 2

    state = secrets.token_urlsafe(16)
    url = f"{_AUTH}?" + urllib.parse.urlencode(
        {
            "client_id": app_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
        }
    )

    server = http.server.HTTPServer(("localhost", 8085), _Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()

    print("\nOpening Pinterest authorisation in your browser.")
    print("If it does not open, paste this URL:\n")
    print(f"  {url}\n")
    webbrowser.open(url)
    print("Waiting for the redirect back to localhost:8085 ...")

    # The handler thread above serves exactly one request, which is all the
    # redirect needs. Poll for it rather than blocking forever, so a browser
    # that never comes back times out instead of hanging the terminal.
    import time

    for _ in range(300):
        if _received:
            break
        time.sleep(1)

    if _received.get("state") != state:
        # A mismatched state means the response did not come from the request
        # this process started. Refusing is the whole point of sending one.
        print(f"state mismatch - aborting. got: {_received}", file=sys.stderr)
        return 1
    code = _received.get("code")
    if not code:
        print(f"no authorisation code returned: {_received}", file=sys.stderr)
        return 1

    basic = base64.b64encode(f"{app_id}:{app_secret}".encode()).decode()
    resp = requests.post(
        _TOKEN,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            # Ask for the indefinitely-refreshable token explicitly. Apps created
            # before 25 Sep 2025 default to the legacy 365-day-hard-limit refresh
            # token unless this is set, and that one eventually dies for good.
            "continuous_refresh": "true",
        },
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=40,
    )
    if resp.status_code != 200:
        print(f"token exchange failed: HTTP {resp.status_code} {resp.text[:300]}", file=sys.stderr)
        return 1

    payload = resp.json()
    access = payload.get("access_token", "")
    refresh = payload.get("refresh_token", "")
    print("\n  access token   :", f"{access[:12]}... ({payload.get('expires_in', 0) // 86400}d)")
    print("  refresh token  :", f"{refresh[:12]}... ({payload.get('refresh_token_expires_in', 0) // 86400}d, refreshable indefinitely)")

    import subprocess

    py = sys.executable
    for key, value in (
        ("PINTEREST_APP_ID", app_id),
        ("PINTEREST_APP_SECRET", app_secret),
        ("PINTEREST_TOKEN", access),
        ("PINTEREST_REFRESH_TOKEN", refresh),
    ):
        if value:
            # Through set_env.py, never by writing .env from here: PowerShell and
            # ad-hoc writers have mangled this file's encoding before.
            subprocess.run([py, str(AGENT_ROOT / "tools" / "set_env.py"), f"{key}={value}"],
                           check=False)

    print("\nNow verify and create a board if you have none:")
    print("  python tools/preflight.py --live")
    print("  python tools/pinterest_auth.py --boards")
    return 0


def refresh_now() -> int:
    """Refresh the access token and PERSIST whatever came back.

        python tools/pinterest_auth.py --refresh

    This exists because `PinterestPlatform.refresh()` deliberately only
    *returns* the new values — a Modal container cannot write its own secret, so
    the scheduled job reports them instead. Locally there is no such limit, and
    a refresh that does not persist is worse than none: Pinterest rotates the
    refresh token, so the one left in `.env` may already be spent.

    Written through `set_env.py`, never directly, for the usual encoding reason.
    """
    import subprocess

    sys.path.insert(0, str(AGENT_ROOT))
    from config import CONFIG
    from platforms.pinterest import PinterestPlatform

    ok, detail, values = PinterestPlatform(CONFIG).refresh()
    print(f"  refresh: {ok} - {detail}")
    if not ok:
        return 1
    for key, value in values.items():
        if value:
            subprocess.run(
                [sys.executable, str(AGENT_ROOT / "tools" / "set_env.py"), f"{key}={value}"],
                check=False,
            )

    # Prove the persisted token actually works before declaring success. A
    # refresh that writes a broken value is the failure this whole exercise
    # started with.
    token = _env("PINTEREST_TOKEN")
    resp = requests.get(
        "https://api.pinterest.com/v5/user_account",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    print(f"  persisted token verified: HTTP {resp.status_code}")
    return 0 if resp.status_code == 200 else 1


def show_boards() -> int:
    """List boards, and offer to create one. A Pin with no board 400s."""
    sys.path.insert(0, str(AGENT_ROOT))
    from config import CONFIG
    from platforms.pinterest import PinterestPlatform

    platform = PinterestPlatform(CONFIG)
    ok, items = platform.boards()
    if not ok:
        print("could not list boards - is PINTEREST_TOKEN valid? Run preflight --live.")
        return 1
    if items:
        print(f"{len(items)} board(s):")
        for board in items:
            print(f"  {board.get('id')}  {board.get('name')}")
        print("\nSet the one to pin into:")
        print(f"  python tools/set_env.py PINTEREST_BOARD_ID={items[0].get('id')}")
        return 0

    print("No boards exist. A Pin with no board returns 400, so create one:")
    name = input("  board name [WizCodes Work]: ").strip() or "WizCodes Work"
    resp = requests.post(
        "https://api.pinterest.com/v5/boards",
        json={"name": name, "description": "Web, mobile and AI work by WizCodes.",
              "privacy": "PUBLIC"},
        headers={"Authorization": f"Bearer {CONFIG.pinterest_token}"},
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        print(f"  failed: HTTP {resp.status_code} {resp.text[:200]}")
        return 1
    board_id = resp.json().get("id")
    print(f"  created board {board_id}")
    print(f"  python tools/set_env.py PINTEREST_BOARD_ID={board_id}")
    return 0


if __name__ == "__main__":
    if "--boards" in sys.argv:
        sys.exit(show_boards())
    sys.exit(refresh_now() if "--refresh" in sys.argv else main())
