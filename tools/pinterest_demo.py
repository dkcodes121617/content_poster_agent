"""A screen-recordable demonstration of this app using the Pinterest API.

    python tools/pinterest_demo.py --sandbox          # the one to record
    python tools/pinterest_demo.py --sandbox --oauth  # include the live OAuth flow
    python tools/pinterest_demo.py --production       # read-only proof against live

## Why this file exists

Pinterest's upgrade from Trial to Standard access asks for "a video recording of
your app completing an action using the Pinterest API". That instruction assumes
a consumer app with screens. This app has none — it is a headless agent that
runs on a schedule — so there is nothing to point a camera at until something
puts the same evidence on screen deliberately.

That is all this is. It performs the real calls the agent performs, against the
real API, with the real credentials, and narrates each step so a reviewer
watching a recording can follow what happened.

## Why --sandbox is the mode to record

Trial access cannot create Pins in production; the API returns

    403 {"code": 29, "message": "Apps with Trial access may not create Pins in
    production ... use API Sandbox instead"}

It CAN create them in Sandbox, and Sandbox Pins are visible on your own Pinterest
profile — so the recording shows a Pin genuinely being created through the API
rather than an error. That is the action Pinterest is asking to see.

Sandbox needs its OWN token; the production OAuth token returns 401 there. Get
one from the app's Configure tab -> Generate Access Token -> environment
"Sandbox" -> Generate token, then store it with tools/set_env.py.

## Nothing here prints a secret

Tokens are shown as a short prefix only. A recording is a file that gets
uploaded to a third party, and a credential visible for two frames is a
credential that has been disclosed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

AGENT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_ROOT))

PRODUCTION = "https://api.pinterest.com/v5"
SANDBOX = "https://api-sandbox.pinterest.com/v5"

# A real, publicly reachable image. Pinterest FETCHES the URL server-side, so it
# must be public — a localhost path or a data URI fails with a fetch error that
# reads like an auth problem and is not one.
FALLBACK_IMAGE = "https://wizcodes.site/og.png"


def banner(step: str, title: str) -> None:
    print()
    print("=" * 72)
    print(f"  STEP {step}   {title}")
    print("=" * 72)
    # A recording is watched, not scrubbed. The pause gives a viewer time to
    # read the heading before output scrolls underneath it.
    time.sleep(1.2)


def show(label: str, value: str) -> None:
    print(f"    {label:<22} {value}")


def call(method: str, base: str, path: str, token: str, **kw) -> requests.Response:
    url = f"{base}{path}"
    print(f"\n  -> {method} {url}")
    resp = requests.request(
        method, url, headers={"Authorization": f"Bearer {token}"}, timeout=30, **kw
    )
    print(f"  <- HTTP {resp.status_code}")
    return resp


def main() -> int:
    ap = argparse.ArgumentParser(description="Recordable Pinterest API demo.")
    env = ap.add_mutually_exclusive_group()
    env.add_argument("--sandbox", action="store_true", help="Sandbox (record this one)")
    env.add_argument("--production", action="store_true", help="production, read-only")
    ap.add_argument("--oauth", action="store_true", help="run the live OAuth flow first")
    ap.add_argument("--image", default="", help="public image URL for the Pin")
    args = ap.parse_args()

    from dotenv import load_dotenv

    load_dotenv(AGENT_ROOT / ".env")

    sandbox = not args.production
    base = SANDBOX if sandbox else PRODUCTION

    if args.oauth:
        banner("0", "Live Pinterest OAuth - real login and consent screen")
        print("  A browser window opens on pinterest.com. Sign in and press Allow.")
        print("  Keep this visible in the recording: a missing OAuth consent screen")
        print("  is the single most common reason an upgrade request is refused.\n")
        from tools import pinterest_auth

        if pinterest_auth.main() != 0:
            print("\n  OAuth did not complete; stopping.", file=sys.stderr)
            return 1
        load_dotenv(AGENT_ROOT / ".env", override=True)

    var = "PINTEREST_SANDBOX_TOKEN" if sandbox else "PINTEREST_TOKEN"
    token = os.environ.get(var, "")
    if not token:
        print(f"\n  {var} is not set.", file=sys.stderr)
        if sandbox:
            print(
                "\n  Get one from developers.pinterest.com -> your app -> Configure ->\n"
                "  Generate Access Token -> environment Sandbox -> Generate token.\n"
                "  Then store it:\n"
                "      python tools/set_env.py PINTEREST_SANDBOX_TOKEN=<token>",
                file=sys.stderr,
            )
        return 2

    banner("1", "Which app and account is calling")
    show("App ID", os.environ.get("PINTEREST_APP_ID", "<not set>"))
    show("Environment", "Sandbox" if sandbox else "Production")
    show("API base", base)
    show("Token", f"{token[:8]}... ({len(token)} chars)")

    banner("2", "Authenticate - GET /user_account")
    resp = call("GET", base, "/user_account", token)
    if not resp.ok:
        print(f"  {resp.text[:300]}", file=sys.stderr)
        return 1
    account = resp.json()
    show("Business name", str(account.get("business_name") or account.get("username")))
    show("Account type", str(account.get("account_type")))
    show("Account id", str(account.get("id")))

    banner("3", "List boards - GET /boards")
    resp = call("GET", base, "/boards", token)
    boards = resp.json().get("items", []) if resp.ok else []
    for board in boards:
        show(str(board.get("name")), str(board.get("id")))

    board_id = boards[0]["id"] if boards else None
    if not board_id:
        banner("3b", "No board yet - POST /boards")
        resp = call(
            "POST", base, "/boards", token,
            json={"name": "WizCodes", "description": "Work from wizcodes.site"},
        )
        if not resp.ok:
            print(f"  {resp.text[:300]}", file=sys.stderr)
            return 1
        board_id = resp.json()["id"]
        show("Created board", board_id)

    if args.production:
        print("\n  Read-only in production: Trial access cannot create Pins here.")
        print("  Re-run with --sandbox to record a Pin actually being created.")
        return 0

    banner("4", "Create a Pin - POST /pins")
    image = args.image or FALLBACK_IMAGE
    show("Board", str(board_id))
    show("Image URL", image)
    resp = call(
        "POST", base, "/pins", token,
        json={
            "board_id": board_id,
            "title": "How we build software at WizCodes",
            "description": "Custom websites, mobile apps and AI automation.",
            "link": "https://wizcodes.site",
            "media_source": {"source_type": "image_url", "url": image},
        },
    )
    if not resp.ok:
        print(f"\n  Pin creation failed: {resp.text[:400]}", file=sys.stderr)
        return 1

    pin = resp.json()
    banner("5", "Done - the Pin exists")
    show("Pin id", str(pin.get("id")))
    show("Board id", str(pin.get("board_id")))
    show("Link", str(pin.get("link")))
    print("\n  Full API response:\n")
    print(json.dumps(pin, indent=2)[:1200])
    print("\n  This Pin is visible on your own Pinterest profile.")
    print("  Show it there to close the recording.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
