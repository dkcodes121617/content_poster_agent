"""Content Poster — configuration check, and optionally a live credential test.

    python tools/preflight.py           # config only
    python tools/preflight.py --live    # also call every service this agent uses

Reads only this agent's .env. Nothing outside this folder.
`--live` is read-only: it never posts. A missing credential is SKIP, not FAIL.
"""
from __future__ import annotations

import sys
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent

SPEC: dict[str, tuple[bool, str]] = {
    "ANTHROPIC_BASE_URL":          (True,  "drafting"),
    "ANTHROPIC_API_KEY":           (True,  "drafting"),
    "NEON_DATABASE_URL":           (True,  "the approval checkpoint - no durable pause without it"),
    "LANGGRAPH_CHECKPOINT_SCHEMA": (True,  "durable graph state; must be unique per agent"),
    "TELEGRAM_BOT_TOKEN":          (True,  "approval requests"),
    "TELEGRAM_CHAT_ID":            (True,  "approval requests"),
    "TELEGRAM_CALLBACK_PREFIX":    (True,  "routing button presses back to this agent"),
    "SITE_REPO":                   (True,  "grounding facts - without them the model invents a client"),
    "SITE_READ_TOKEN":             (True,  "grounding facts (read-only PAT)"),
    "R2_ACCESS_KEY_ID":            (True,  "image storage"),
    "R2_SECRET_ACCESS_KEY":        (True,  "image storage"),
    "R2_BUCKET_ENDPOINT":          (True,  "image storage"),
    "R2_BUCKET_NAME":              (True,  "image storage"),
    "R2_PUBLIC_BASE_URL":          (True,  "ALL Meta posts - Meta fetches the image by URL"),
    "PLATFORMS_ENABLED":           (True,  "which platforms publish"),
    "META_APP_ID":                 (True,  "Facebook publishing"),
    "META_APP_SECRET":             (True,  "Facebook publishing"),
    "META_PAGE_ID":                (True,  "Facebook publishing"),
    "META_PAGE_ACCESS_TOKEN":      (True,  "Facebook publishing"),
    "META_GRAPH_VERSION":          (True,  "pinning - an unpinned version fails on Meta's schedule"),
    "THREADS_ACCESS_TOKEN":        (True,  "Threads publishing"),
    "HUGGINGFACE_TOKEN":           (True,  "image generation"),
    "BRAND_FONT_PATH":             (True,  "the brand mark on every image"),
    "DRY_RUN":                     (True,  "the kill switch must be explicit, never defaulted"),
    "INSTAGRAM_APP_ACCESS_TOKEN":  (True,  "Instagram publishing (Instagram Login path)"),
    "INSTAGRAM_USER_ID":           (True,  "Instagram publishing"),
    "GROQ_API_KEY":                (False, "fallback drafting only"),
    "DEVTO_API_KEY":               (False, "blog syndication to dev.to"),
    "PINTEREST_TOKEN":             (False, "Pinterest pins"),
    # NOT required: the Facebook-Page-linked Instagram id. Instagram publishes
    # through its own Login path (graph.instagram.com), so the restricted
    # Business Portfolio link never blocked anything.
    "META_IG_BUSINESS_ACCOUNT_ID": (False, "unused - superseded by the Instagram Login path"),
    "LINKEDIN_ACCESS_TOKEN":       (False, "LinkedIn only - blocked on API review"),
    "LINKEDIN_ORG_ID":             (False, "LinkedIn only - blocked on API review"),
}


def load() -> dict[str, str]:
    out: dict[str, str] = {}
    env = AGENT_ROOT / ".env"
    if not env.exists():
        sys.exit(f"no .env at {env}")
    for line in env.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def check_config(env: dict[str, str]) -> int:
    print("\nCONFIG")
    print("------")
    missing = 0
    for name, (required, blocks) in SPEC.items():
        if env.get(name, ""):
            print(f"  [ok]      {name}")
        elif required:
            missing += 1
            print(f"  [MISSING] {name:<30} blocks: {blocks}")
        else:
            print(f"  [ - ]     {name:<30} optional: {blocks}")
    # Assert only what the enabled platforms actually need — the whole point of
    # PLATFORMS_ENABLED is that a blocked platform costs nothing.
    enabled = [p.strip() for p in env.get("PLATFORMS_ENABLED", "").split(",") if p.strip()]
    print(f"\n  platforms enabled: {', '.join(enabled) or '(none)'}")
    # Instagram publishes via its OWN Login path (graph.instagram.com), so what
    # it needs is an Instagram User token, not the Facebook-Page-linked id. The
    # earlier version asserted META_IG_BUSINESS_ACCOUNT_ID here and would have
    # kept Instagram switched off indefinitely over a link that publishing never
    # required.
    if "instagram" in enabled:
        for k in ("INSTAGRAM_APP_ACCESS_TOKEN", "INSTAGRAM_USER_ID"):
            if not env.get(k):
                print(f"  [MISSING] instagram is enabled but {k} is blank")
                missing += 1
    if "linkedin" in enabled and not env.get("LINKEDIN_ACCESS_TOKEN"):
        print("  [MISSING] linkedin is enabled but LINKEDIN_ACCESS_TOKEN is blank")
        missing += 1
    return missing


def check_live(env: dict[str, str]) -> int:
    import requests

    print("\nLIVE (read-only - nothing is published)")
    print("---------------------------------------")
    failures = 0

    enabled = {p.strip() for p in env.get("PLATFORMS_ENABLED", "").split(",") if p.strip()}

    def run(label: str, key: str, fn, platform: str = ""):
        """`platform` names the platform this check belongs to, if any.

        A broken credential for a platform that is NOT in PLATFORMS_ENABLED is
        reported as WARN rather than FAIL, and does not block the deploy. That
        is the same principle the config section already applies: a disabled
        platform costs nothing. An expired Pinterest token should not stop
        Facebook, Threads and Instagram from shipping — but it must still be
        visible, because "not enabled" and "quietly broken" have to stay
        distinguishable.
        """
        nonlocal failures
        if not key:
            print(f"  SKIP  {label:<22} not set")
            return
        optional = bool(platform) and platform not in enabled
        try:
            ok, detail = fn()
            status = "PASS" if ok else ("WARN" if optional else "FAIL")
            suffix = "  (platform not enabled)" if (optional and not ok) else ""
            print(f"  {status}  {label:<22} {detail[:74]}{suffix}")
            if not ok and not optional:
                failures += 1
        except Exception as e:
            status = "WARN" if optional else "FAIL"
            print(f"  {status}  {label:<22} {type(e).__name__}: {str(e)[:58]}")
            if not optional:
                failures += 1

    V = env.get("META_GRAPH_VERSION", "v26.0")

    def claude():
        r = requests.post(f"{env['ANTHROPIC_BASE_URL']}/v1/messages",
            headers={"x-api-key": env["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
                     "content-type": "application/json",
                     "user-agent": "claude-cli/1.0.0 (external, cli)"},
            json={"model": env["ANTHROPIC_MODEL"], "max_tokens": 8,
                  "messages": [{"role": "user", "content": "Reply with: ok"}]}, timeout=60)
        return r.status_code == 200, f"HTTP {r.status_code}"

    def neon():
        import psycopg
        with psycopg.connect(env["NEON_DATABASE_URL"], connect_timeout=20) as c:
            v = c.execute("SHOW server_version").fetchone()[0]
            s = c.execute("SELECT count(*) FROM pg_namespace WHERE nspname=%s",
                          (env["LANGGRAPH_CHECKPOINT_SCHEMA"],)).fetchone()[0]
            return s == 1, f"PG {v}, checkpoint schema '{env['LANGGRAPH_CHECKPOINT_SCHEMA']}' present={bool(s)}"

    def telegram():
        r = requests.get(f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/getMe", timeout=25).json()
        return bool(r.get("ok")), f"@{(r.get('result') or {}).get('username')}"

    def github():
        r = requests.get(f"https://api.github.com/repos/{env['SITE_REPO']}",
                         headers={"Authorization": f"Bearer {env['SITE_READ_TOKEN']}"}, timeout=25)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        warn = "  <- NOT read-only (has push/admin)" if r.json().get("permissions", {}).get("push") else ""
        return True, f"{r.json().get('full_name')}{warn}"

    def r2():
        import boto3
        from botocore.config import Config
        s3 = boto3.client("s3", endpoint_url=env["R2_BUCKET_ENDPOINT"],
                          aws_access_key_id=env["R2_ACCESS_KEY_ID"],
                          aws_secret_access_key=env["R2_SECRET_ACCESS_KEY"],
                          region_name="auto", config=Config(signature_version="s3v4"))
        s3.list_objects_v2(Bucket=env["R2_BUCKET_NAME"], MaxKeys=1)
        # The public URL matters more than the bucket: Meta FETCHES by URL, so a
        # bucket that only the agent can read fails every post.
        pub = requests.get(env["R2_PUBLIC_BASE_URL"].rstrip("/") + "/_preflight_probe", timeout=20)
        reachable = pub.status_code in (200, 404)   # 404 = serving, object absent
        return reachable, f"bucket ok; public URL {'reachable' if reachable else f'BROKEN ({pub.status_code})'}"

    def meta():
        r = requests.get(f"https://graph.facebook.com/{V}/me",
                         params={"fields": "id,name", "access_token": env["META_PAGE_ACCESS_TOKEN"]},
                         timeout=25).json()
        if "error" in r:
            return False, r["error"].get("message", "")[:70]
        return r.get("id") == env.get("META_PAGE_ID"), f"{r.get('name')} ({r.get('id')})"

    def meta_expiry():
        r = requests.get(f"https://graph.facebook.com/{V}/debug_token",
                         params={"input_token": env["META_PAGE_ACCESS_TOKEN"],
                                 "access_token": f"{env['META_APP_ID']}|{env['META_APP_SECRET']}"},
                         timeout=25).json().get("data", {})
        exp = r.get("expires_at")
        # 0 means never. Anything else is a clock you have to watch.
        return exp == 0, f"type={r.get('type')} expires={'NEVER' if exp == 0 else exp}"

    def instagram():
        """Instagram Login path — graph.instagram.com, NOT the Facebook Page link.

        The Page-linked route (graph.facebook.com/<ig_business_id>/media) needs a
        Business Portfolio link that Meta has restricted on this account. It was
        never actually required: an Instagram User token carrying
        instagram_business_content_publish publishes directly, with no Facebook
        Page in the loop at all. That is what this checks."""
        base = env.get("INSTAGRAM_API_BASE", "https://graph.instagram.com/v23.0")
        tok = env["INSTAGRAM_APP_ACCESS_TOKEN"]
        me = requests.get(f"{base}/me",
                          params={"fields": "id,username,account_type", "access_token": tok},
                          timeout=25).json()
        if "error" in me:
            return False, str(me["error"].get("message"))[:70]
        if me.get("account_type") not in ("BUSINESS", "CREATOR"):
            return False, f"account_type={me.get('account_type')} — publishing needs BUSINESS/CREATOR"
        # The decisive check: this endpoint only answers for a token that holds
        # instagram_business_content_publish. A missing scope is a permissions
        # error here, not a quota reading.
        q = requests.get(f"{base}/me/content_publishing_limit",
                         params={"access_token": tok}, timeout=25).json()
        if "error" in q:
            return False, f"@{me.get('username')} but NO publish scope: {str(q['error'].get('message'))[:45]}"
        used = (q.get("data") or [{}])[0].get("quota_usage")
        return True, f"@{me.get('username')} {me.get('account_type')}, publish OK, quota used {used}/50"

    def devto():
        r = requests.get("https://dev.to/api/users/me",
                         headers={"api-key": env["DEVTO_API_KEY"]}, timeout=25)
        return r.status_code == 200, (f"@{r.json().get('username')}" if r.status_code == 200
                                      else f"HTTP {r.status_code}")

    def pinterest():
        r = requests.get("https://api.pinterest.com/v5/user_account",
                         headers={"Authorization": f"Bearer {env['PINTEREST_TOKEN']}"}, timeout=25)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code} {r.text[:50]}"
        d = r.json()
        b = requests.get("https://api.pinterest.com/v5/boards",
                         headers={"Authorization": f"Bearer {env['PINTEREST_TOKEN']}"},
                         params={"page_size": 1}, timeout=25)
        n = len(b.json().get("items") or []) if b.status_code == 200 else 0
        # A Pin needs a board. Zero boards means every publish would 400.
        warn = "  <- NO BOARD YET, create one before posting" if n == 0 else ""
        return True, f"{d.get('account_type')}, {d.get('board_count', 0)} board(s){warn}"

    def threads():
        r = requests.get("https://graph.threads.net/v1.0/me",
                         params={"fields": "id,username", "access_token": env["THREADS_ACCESS_TOKEN"]},
                         timeout=25).json()
        return "error" not in r, f"@{r.get('username')}" if "error" not in r else str(r["error"])[:60]

    def hf():
        r = requests.get("https://huggingface.co/api/whoami-v2",
                         headers={"Authorization": f"Bearer {env['HUGGINGFACE_TOKEN']}"}, timeout=25)
        return r.status_code == 200, f"user {r.json().get('name')}" if r.status_code == 200 else f"HTTP {r.status_code}"

    def fonts():
        from PIL import ImageFont
        found = []
        for p in sorted((AGENT_ROOT / "assets").glob("*.ttf")):
            f = ImageFont.truetype(str(p), 32)
            found.append("-".join(f.getname()))
        return bool(found), ", ".join(found) or "no .ttf in assets/ - run tools/fetch_brand_fonts.py"

    run("Claude proxy", env.get("ANTHROPIC_API_KEY", ""), claude)
    run("Neon", env.get("NEON_DATABASE_URL", ""), neon)
    run("Telegram", env.get("TELEGRAM_BOT_TOKEN", ""), telegram)
    run("Site repo (PAT)", env.get("SITE_READ_TOKEN", ""), github)
    run("R2 + public URL", env.get("R2_ACCESS_KEY_ID", ""), r2)
    run("Meta Page token", env.get("META_PAGE_ACCESS_TOKEN", ""), meta, "facebook")
    run("Meta token expiry", env.get("META_PAGE_ACCESS_TOKEN", ""), meta_expiry, "facebook")
    run("Instagram publish", env.get("INSTAGRAM_APP_ACCESS_TOKEN", ""), instagram, "instagram")
    run("Threads token", env.get("THREADS_ACCESS_TOKEN", ""), threads, "threads")
    run("HuggingFace", env.get("HUGGINGFACE_TOKEN", ""), hf)
    run("dev.to", env.get("DEVTO_API_KEY", ""), devto, "devto")
    run("Pinterest", env.get("PINTEREST_TOKEN", ""), pinterest, "pinterest")
    run("Brand fonts", "always", fonts)
    return failures


def main() -> int:
    env = load()
    missing = check_config(env)
    failures = check_live(env) if "--live" in sys.argv else 0
    print()
    if missing:
        print(f"{missing} required variable(s) missing.")
    if failures:
        print(f"{failures} live check(s) failed.")
    if not missing and not failures:
        print("content_poster_agent: ready.")
    return 1 if (missing or failures) else 0


if __name__ == "__main__":
    sys.exit(main())
