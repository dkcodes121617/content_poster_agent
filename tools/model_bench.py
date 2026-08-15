"""Benchmark the LLMsRelay proxy's models on the three jobs the agents do.

    python tools/model_bench.py              # all models, all jobs
    python tools/model_bench.py --job voice  # one job

Model choice is not a matter of picking the biggest. Each agent has a different
failure mode, so each is measured against the thing that actually breaks it:

  voice    Social copy. The failure is prose that reads AI-generated, which is
           the one thing CAMPAIGN.md §3 exists to prevent. Scored on the banned-
           phrase list, sentence-length variance (uniform lengths are the
           strongest tell), and whether the model used the grounding facts given
           rather than inventing its own.
  json     Lead classification. High volume, low stakes, but the output is
           parsed — a model that emits prose around its JSON fails the whole
           run. Scored on strict-parse rate and latency, nothing else.
  email    Cold outreach. Scored on the hard constraints from EMAIL_PLAYBOOK.md
           §3: under 125 words, at most one link, no marketing vocabulary.

Latency matters differently per job too: a 12-second call is fine for one social
post a day and fatal for classifying 300 candidates.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

import requests

AGENT_ROOT = Path(__file__).resolve().parent.parent

MODELS = [
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-opus-4-8",
    "claude-sonnet-4.6",
    "claude-haiku-4.5",
]

# From CAMPAIGN.md §3. Any hit is a voice-gate rejection in production.
BANNED = [
    "delve", "in today's", "fast-paced", "unlock", "elevate", "game-chang",
    "seamless", "revolutionis", "revolutioniz", "leverage", "robust solution",
    "cutting-edge", "empower", "dive in", "🚀", "thoughts?",
    "it's not just", "it is not just", "in the world of", "landscape of",
]

GROUNDING = """REAL WIZCODES FACTS (use only these; invent nothing):
- CuePilot — real-time cue system, sub-200ms median response.
- SolarSathi — solar-installer field app, India.
- ClarivueXAI — open-source explainability library, 1000+ PyPI downloads.
- Offer: a free working prototype before any payment. No discovery fee.
- Services: Web Development, Mobile Apps, AI Automation.
- Site: wizcodes.site"""

JOBS = {
    "voice": {
        "max_tokens": 500,
        "prompt": GROUNDING + """

Write one LinkedIn post for WizCodes, a small software studio.
Angle: proof — a real project and what it took.
120-180 words. Open on a concrete tension, not on context. One idea only.
Plain text. No hashtags. No emoji. End with a real next step or nothing.""",
    },
    "json": {
        "max_tokens": 300,
        "prompt": """Classify this forum post as a sales lead for a software studio
offering Web Development, Mobile Apps and AI Automation.

POST: "Running a small dental practice in Leeds. Our booking page is from 2016,
takes forever on mobile, and half our patients just phone instead. Losing about
nine appointments a week to no-shows because there are no reminders. Not sure if
this is worth fixing or if I should just hire a receptionist."

Respond with ONLY a JSON object, no prose before or after:
{"is_lead": bool, "confidence": "low"|"medium"|"high",
 "service_line": "Web Development"|"Mobile Apps"|"AI Automation"|"none",
 "intent_score": 0-100, "reasoning": "one sentence", "reply_angle": "one sentence"}""",
    },
    "email": {
        "max_tokens": 400,
        "prompt": GROUNDING + """

Write a cold email to the owner of a dental clinic. What we found on their site:
loads in 6.2s on mobile, no viewport meta tag, copyright footer says 2016,
booking form is a mailto: link.

HARD RULES: under 125 words. Plain text. At most ONE link, zero is better.
Subject line: 2-4 words, lowercase, no punctuation.
Open with the specific thing we noticed. Sound like one person writing to another.
Format exactly as:
SUBJECT: <subject>
BODY:
<body>""",
    },
}


def load_env() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (AGENT_ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def call(env: dict[str, str], model: str, prompt: str, max_tokens: int) -> tuple[str, float, str]:
    t0 = time.time()
    try:
        r = requests.post(
            f"{env['ANTHROPIC_BASE_URL']}/v1/messages",
            headers={
                "x-api-key": env["ANTHROPIC_API_KEY"],
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
                # Cloudflare in front of the proxy 403s any non-CLI User-Agent.
                "user-agent": "claude-cli/1.0.0 (external, cli)",
            },
            json={"model": model, "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=180,
        )
        dt = time.time() - t0
        if r.status_code != 200:
            return "", dt, f"HTTP {r.status_code}"
        return "".join(b.get("text", "") for b in r.json().get("content", [])), dt, ""
    except Exception as e:
        return "", time.time() - t0, f"{type(e).__name__}"


def score_voice(text: str) -> dict:
    low = text.lower()
    hits = [b for b in BANNED if b in low]
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 3]
    lens = [len(s.split()) for s in sentences]
    # Uniform sentence length is the strongest AI tell there is. Variance is a
    # crude proxy for rhythm, but it correlates and it is cheap to compute.
    variance = statistics.pstdev(lens) if len(lens) > 1 else 0.0
    facts = ["cuepilot", "solarsathi", "clarivuexai", "200ms", "prototype"]
    grounded = sum(1 for f in facts if f in low)
    # Invented specifics: a percentage or dollar figure we never supplied.
    invented = re.findall(r"\b\d+%|\$\d[\d,]*", text)
    return {"words": len(text.split()), "banned": hits, "variance": round(variance, 1),
            "grounded": grounded, "invented": invented, "sentences": len(sentences)}


def score_json(text: str) -> dict:
    raw = text.strip()
    # A model that fences its JSON is still usable; one that writes prose around
    # it needs an extractor, which is where classification pipelines break.
    fenced = raw.startswith("```")
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    ok, obj = False, {}
    if m:
        try:
            obj = json.loads(m.group(0))
            ok = True
        except Exception:
            ok = False
    clean = ok and not fenced and raw.startswith("{") and raw.endswith("}")
    keys = {"is_lead", "confidence", "service_line", "intent_score", "reasoning", "reply_angle"}
    return {"parsed": ok, "clean": clean, "fenced": fenced,
            "complete": ok and keys.issubset(obj.keys()),
            "score": obj.get("intent_score"), "line": obj.get("service_line")}


def score_email(text: str) -> dict:
    body = text.split("BODY:", 1)[1] if "BODY:" in text else text
    subj_m = re.search(r"SUBJECT:\s*(.+)", text)
    subj = subj_m.group(1).strip() if subj_m else ""
    low = text.lower()
    return {"words": len(body.split()), "subject": subj,
            "subject_words": len(subj.split()),
            "subject_ok": bool(subj) and len(subj.split()) <= 4 and subj == subj.lower(),
            "links": len(re.findall(r"https?://|www\.", body)),
            "banned": [b for b in BANNED if b in low],
            "under_125": len(body.split()) <= 125}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", choices=[*list(JOBS), "all"], default="all")
    ap.add_argument("--runs", type=int, default=2)
    args = ap.parse_args()
    env = load_env()
    jobs = list(JOBS) if args.job == "all" else [args.job]

    for job in jobs:
        spec = JOBS[job]
        print(f"\n{'=' * 78}\nJOB: {job}   ({args.runs} run(s) per model)\n{'=' * 78}")
        for model in MODELS:
            lat, results, errs = [], [], []
            for _ in range(args.runs):
                text, dt, err = call(env, model, spec["prompt"], spec["max_tokens"])
                lat.append(dt)
                if err:
                    errs.append(err)
                    continue
                results.append({"voice": score_voice, "json": score_json,
                                "email": score_email}[job](text))
            med = statistics.median(lat)
            if not results:
                print(f"  {model:<20} FAILED  {errs}")
                continue
            r0 = results[0]
            if job == "voice":
                b = sum(len(r["banned"]) for r in results)
                inv = sum(len(r["invented"]) for r in results)
                g = statistics.mean(r["grounded"] for r in results)
                v = statistics.mean(r["variance"] for r in results)
                print(f"  {model:<20} {med:5.1f}s  banned={b}  invented={inv}  "
                      f"grounded={g:.1f}/5  rhythm={v:.1f}  words={r0['words']}")
            elif job == "json":
                p = sum(r["parsed"] for r in results)
                c = sum(r["clean"] for r in results)
                comp = sum(r["complete"] for r in results)
                print(f"  {model:<20} {med:5.1f}s  parsed={p}/{len(results)}  "
                      f"bare-json={c}/{len(results)}  all-keys={comp}/{len(results)}  "
                      f"score={r0['score']} line={r0['line']}")
            else:
                ok = sum(r["under_125"] for r in results)
                s = sum(r["subject_ok"] for r in results)
                b = sum(len(r["banned"]) for r in results)
                lk = statistics.mean(r["links"] for r in results)
                print(f"  {model:<20} {med:5.1f}s  <=125w={ok}/{len(results)}  "
                      f"subj_ok={s}/{len(results)}  banned={b}  links={lk:.1f}  "
                      f"words={r0['words']}  subj={r0['subject'][:28]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
