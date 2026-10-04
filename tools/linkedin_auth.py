"""One-time LinkedIn OAuth for the Community Management API.

    python tools/linkedin_auth.py           authorise, find ids, save tokens
    python tools/linkedin_auth.py --check   verify the saved token still works

## What the Development tier gives this agent

Approved Community Management API access (Development tier) grants, per
LinkedIn's "Increasing Access" page (li-lms-2026-09):

  * `w_organization_social` / `r_organization_social` / `rw_organization_admin`
    - post as the WizCodes company page, read its posts and page analytics

It also offers personal-profile posting (`w_member_social`); this agent does not
request it - WizCodes posts as the company page only.

Development-tier limits: 500 API calls per app and 100 per member per 24 h, no
BATCH_GET endpoints, no webhooks, and the integration must be finished within
12 months - then apply for Standard tier with a screencast of every use case.

## What you need first

In the app at https://www.linkedin.com/developers/apps :

  1. Products tab: "Community Management API" shows as added (Development).
  2. Auth tab: copy the Client ID and Client Secret.
  3. Auth tab -> OAuth 2.0 settings -> Authorized redirect URLs, add exactly:
         http://localhost:8086/callback
  4. Sign in to LinkedIn in your browser as a person who is an ADMINISTRATOR of
     the WizCodes company page - posting as the page requires that role.

Tokens last 60 days. If LinkedIn issues a refresh token to this app (365 days),
it is saved too; otherwise re-run this tool before the access token expires.
"""
from __future__ import annotations

import http.server
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

import requests

AGENT_ROOT = Path(__file__).resolve().parent.parent
REDIRECT_URI = "http://localhost:8086/callback"
# Company page only - the owner's decision (4 Oct): the agent posts as WizCodes,
# never as a person, so no member-level scope is requested. These three cover
# posting as the page, reading its posts back, and its analytics/admin lookup.
SCOPES = " ".join([
    "w_organization_social",
    "r_organization_social",
    "rw_organization_admin",
])
_AUTH = "https://www.linkedin.com/oauth/v2/authorization"
_TOKEN = "https://www.linkedin.com/oauth/v2/accessToken"
_API = "https://api.linkedin.com"
# Keep in step with platforms/linkedin.py. LinkedIn sunsets each monthly version
# about a year after release and rejects requests that name a retired one.
_VERSION = "202609"

_received: dict[str, str] = {}


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _received.update({k: v[0] for k, v in params.items()})
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        body = (
            "<h2>LinkedIn authorised.</h2><p>You can close this tab and return "
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
    try:
        return input(prompt).strip()
    except (EOFError, OSError):
        return ""


def _save(pairs: list[tuple[str, str]]) -> None:
    # Through set_env.py, never by writing .env from here: PowerShell and ad-hoc
    # writers have mangled this file's encoding before.
    for key, value in pairs:
        if value:
            subprocess.run(
                [sys.executable, str(AGENT_ROOT / "tools" / "set_env.py"), f"{key}={value}"],
                check=False,
            )


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "LinkedIn-Version": _VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }


def _admin_orgs(token: str) -> list[str]:
    resp = requests.get(
        f"{_API}/rest/organizationAcls",
        params={"q": "roleAssignee", "role": "ADMINISTRATOR", "state": "APPROVED"},
        headers=_headers(token),
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"  could not list your pages: HTTP {resp.status_code} {resp.text[:200]}")
        return []
    orgs = []
    for element in resp.json().get("elements", []):
        urn = str(element.get("organization") or element.get("organizationTarget") or "")
        if urn.startswith("urn:li:organization:"):
            orgs.append(urn.rsplit(":", 1)[-1])
    return orgs


def main() -> int:
    client_id = _env("LINKEDIN_CLIENT_ID") or _ask("LinkedIn Client ID: ")
    client_secret = _env("LINKEDIN_CLIENT_SECRET") or _ask("LinkedIn Client Secret: ")
    if not (client_id and client_secret):
        print(
            "\nLINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET are both needed - the\n"
            "app's Auth tab at https://www.linkedin.com/developers/apps shows them.\n"
            f"Also add this exact redirect URL there: {REDIRECT_URI}\n",
            file=sys.stderr,
        )
        return 2

    state = secrets.token_urlsafe(16)
    url = f"{_AUTH}?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "scope": SCOPES,
    })

    server = http.server.HTTPServer(("localhost", 8086), _Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()
    print("\nOpening LinkedIn authorisation in your browser.")
    print("Sign in as an ADMINISTRATOR of the WizCodes page. If it does not open:\n")
    print(f"  {url}\n")
    webbrowser.open(url)
    print("Waiting for the redirect back to localhost:8086 ...")
    for _ in range(300):
        if _received:
            break
        time.sleep(1)

    if _received.get("state") != state:
        print(f"state mismatch - aborting. got: {_received}", file=sys.stderr)
        return 1
    code = _received.get("code")
    if not code:
        # LinkedIn reports a scope the app was not granted here, as
        # error=unauthorized_scope_error - usually a product not yet added.
        print(f"no authorisation code returned: {_received}", file=sys.stderr)
        return 1

    resp = requests.post(
        _TOKEN,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=40,
    )
    if resp.status_code != 200:
        print(f"token exchange failed: HTTP {resp.status_code} {resp.text[:300]}", file=sys.stderr)
        return 1
    payload = resp.json()
    access = payload.get("access_token", "")
    refresh = payload.get("refresh_token", "")
    print(f"\n  access token   : {access[:10]}... ({payload.get('expires_in', 0) // 86400}d)")
    if refresh:
        print(f"  refresh token  : {refresh[:10]}... "
              f"({payload.get('refresh_token_expires_in', 0) // 86400}d)")
    else:
        print("  refresh token  : not issued to this app - re-run this tool within 60 days")
    print(f"  scopes granted : {payload.get('scope', '')}")

    orgs = _admin_orgs(access)
    org = ""
    if len(orgs) == 1:
        org = orgs[0]
    elif orgs:
        print("\nYou administer several pages:", ", ".join(orgs))
        org = _ask("Which organization id is WizCodes? ")
    else:
        print("\nNo page found where you are ADMINISTRATOR - posting as the page will "
              "fail until you are made one.")

    print(f"\n  organization   : {org or '(none)'}")
    _save([
        ("LINKEDIN_CLIENT_ID", client_id),
        ("LINKEDIN_CLIENT_SECRET", client_secret),
        ("LINKEDIN_ACCESS_TOKEN", access),
        ("LINKEDIN_REFRESH_TOKEN", refresh),
        ("LINKEDIN_ORG_ID", org),
    ])
    print("\nSaved. Verify with:  python tools/linkedin_auth.py --check")
    return 0


def check() -> int:
    token = _env("LINKEDIN_ACCESS_TOKEN")
    if not token:
        print("LINKEDIN_ACCESS_TOKEN is not set - run: python tools/linkedin_auth.py")
        return 2
    orgs = _admin_orgs(token)
    print(f"pages you administer: {orgs or 'none'}")
    return 0 if orgs else 1


if __name__ == "__main__":
    sys.exit(check() if "--check" in sys.argv else main())
