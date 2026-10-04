"""Fixture content for every format — the design lab's test set.

Two kinds per format:
  * GOOD      realistic WizCodes copy, grounded only in real facts (projects,
              testimonials and counts from the site). Doubles as a showcase.
  * HOSTILE   every text field at its budget limit and every list at its max
              item count, so a budget that the canvas cannot actually hold
              fails a render instead of a post.

Facts used: CuePilot (real-time voice AI, sub-200ms), CraftWorks UK (AI
WhatsApp assistant), Medical OCR pipeline, AI outreach agent, Noorly
(cross-platform contact organiser), 26 projects, 13 testimonials, 11 countries,
free working prototype before any contract, client owns the code.
"""
from __future__ import annotations

from design.registry import FORMATS, Field

GOOD: dict[str, dict] = {
    "hook": {"eyebrow": "For founders hiring a developer", "hook": "Your developer ghosted. Can you still *deploy?*",
             "sub": "What you must own before anyone writes a line of code.", "ticker": "OWNERSHIP"},
    "hot_take": {"eyebrow": "Unpopular opinion", "take": "A discovery phase you pay for is a *sales process* you are funding.",
                 "support": "We build a working prototype first. You judge the work, not the slide deck."},
    "stat": {"eyebrow": "CuePilot", "value": "<200ms", "label": "from a spoken question to an *on-screen answer*",
             "context": "Real-time voice AI for live expert calls. Fast enough that the software disappears.",
             "tiles": [{"value": "26", "label": "projects shipped"}, {"value": "11", "label": "countries"}, {"value": "13", "label": "client testimonials"}],
             "icon": "zap", "source": "CuePilot, a WizCodes build"},
    "chart": {"eyebrow": "Track record", "title": "Where our work has *landed*",
              "series": [{"label": "Projects", "value": 26}, {"label": "Testimonials", "value": 13}, {"label": "Countries", "value": 11}],
              "highlight": "Projects", "source": "wizcodes.site"},
    "quote": {"eyebrow": "How we work", "quote": "If we cannot show you a *working prototype* first, we have not earned the contract.",
              "name": "WizCodes", "role": "founder-run software studio"},
    "myth_fact": {"eyebrow": "Buying software", "title": "The ownership myth", "myth": "Whoever builds the app owns the code.",
                  "fact": "You should own the repo, the hosting and the deploy steps from the *first commit*."},
    "post_card": {"text": "Every project we take on starts the same way:\n\nYou create the repo.\nWe get invited.\n\nIf we vanish tomorrow, you lose nothing but our good company."},
    "notes": {"title": "Before you sign with a dev team", "date": "Saturday 09:14",
              "items": [{"text": "Repo lives in MY GitHub org", "done": True}, {"text": "Hosting billed to my company card", "done": True},
                        {"text": "Credentials in a vault I control", "done": True}, {"text": "Deploy steps written down"},
                        {"text": "See a working prototype before paying"}]},
    "chat": {"eyebrow": "Every week, some version of this", "title": "The question we hear most",
             "messages": [{"from": "them", "text": "Can you just quote me for the whole app?"},
                          {"from": "us", "text": "Rather show you: a working prototype of the core flow first."},
                          {"from": "them", "text": "And if I do not like it?"},
                          {"from": "us", "text": "Then you walk away owing nothing, and you keep the prototype."}],
             "labels": {"them": "Founder", "us": "WizCodes"}},
    "checklist": {"eyebrow": "Before you hire", "title": "Own these from *day one*",
                  "items": [{"text": "Admin access to the code repo", "icon": "git-branch"}, {"text": "Hosting in your company's name", "icon": "database"},
                            {"text": "Credentials in your own vault", "icon": "key-round"}, {"text": "Deploy steps written in the repo", "icon": "rocket"}],
                  "note": "If a developer resists any of these, that is your answer."},
    "cheat_sheet": {"eyebrow": "Save this", "title": "AI automation, *what to automate first*",
                    "cells": [{"head": "Repetitive", "body": "Same steps every time, no judgement calls.", "icon": "repeat"},
                              {"head": "High volume", "body": "Happens daily or many times a week.", "icon": "layers"},
                              {"head": "Costly mistakes", "body": "A typo means a refund or an angry customer.", "icon": "triangle-alert"},
                              {"head": "Clear trigger", "body": "An email, a form or a file kicks it off.", "icon": "zap"},
                              {"head": "Structured data", "body": "Fields you can name, not free-form chat.", "icon": "table"},
                              {"head": "Human review", "body": "Keep a person on anything that touches money.", "icon": "user-check"}]},
    "flags": {"eyebrow": "Hiring a dev team", "title": "Read the *signals* early",
              "red": ["Code lives in their account", "Won't show work before payment", "No written deploy steps", "Quotes before understanding"],
              "green": ["You own the repo from day one", "Working prototype first", "Docs you can follow alone", "Asks about your workflow"]},
    "vs": {"eyebrow": "Choosing how to build", "title": "Off-the-shelf vs *custom*",
           "left": {"label": "Off-the-shelf", "points": ["Fast to start", "Your workflow bends to it", "Data lives in their system"]},
           "right": {"label": "Custom build", "points": ["Fits how you already work", "You own the data model", "Extend it without asking"]},
           "rows": [{"aspect": "Fit", "left": "Generic workflow", "right": "Your workflow"},
                    {"aspect": "Data", "left": "Vendor's database", "right": "Your database"},
                    {"aspect": "Changes", "left": "Feature requests", "right": "You decide"}],
           "winner": "right", "verdict": "Buy for commodity tasks. Build where your *workflow is the advantage*."},
    "steps": {"eyebrow": "How we work", "title": "From idea to *working prototype*",
              "steps": [{"head": "Tell us the problem", "body": "One conversation about the workflow, not the features."},
                        {"head": "We build the core flow", "body": "A clickable, working version you can test."},
                        {"head": "You decide", "body": "Keep going, or walk away owing nothing."}]},
    "framework": {"eyebrow": "A framework we use", "name": "OWN", "title": "Three checks before you hire *anyone*",
                  "pillars": [{"letter": "O", "head": "Organisation account", "body": "The repo and cloud accounts belong to your company."},
                              {"letter": "W", "head": "Written deploy", "body": "Anyone can ship from the repo's own instructions."},
                              {"letter": "N", "head": "No hostage keys", "body": "Every credential sits in a vault you control."}]},
    "tier_list": {"eyebrow": "Opinion", "title": "How to start a software project, *ranked*",
                  "tiers": [{"tier": "S", "items": ["Working prototype"]}, {"tier": "A", "items": ["Clickable mockup", "Written spec"]},
                            {"tier": "B", "items": ["Long discovery phase"]}, {"tier": "C", "items": ["Quote, no questions"]}]},
    "iceberg": {"eyebrow": "What you see vs what it takes", "title": "The *iceberg* of an AI feature",
                "above": ["The chat box", "A smart answer"],
                "below": ["Retrieval over your own data", "Guardrails and refusals", "Evaluation on real questions", "Logging and review", "Cost controls"]},
    "poll": {"eyebrow": "Quick question", "question": "What stops you from *automating* that manual task?",
             "options": ["Not sure where to start", "Worried it will break", "Tools don't fit our workflow", "No time to set it up"],
             "ask": "Pick one in the comments."},
    "decision_tree": {"eyebrow": "Build or buy?", "title": "Should you *build it custom*?",
                      "tree": {"q": "Is the workflow your edge?", "yes": {"q": "Do tools force workarounds?", "yes": "Build it custom", "no": "Configure a tool"},
                               "no": {"q": "Is your data locked in?", "yes": "Plan an export first", "no": "Buy off-the-shelf"}}},
    "timeline": {"eyebrow": "Real project", "title": "How a WhatsApp assistant *took shape*",
                 "events": [{"when": "The problem", "what": "Customer questions piling up in WhatsApp"},
                            {"when": "Prototype", "what": "An assistant answering the top questions"},
                            {"when": "Handover", "what": "Code, keys and docs in the client's accounts"},
                            {"when": "Today", "what": "Live for CraftWorks, United Kingdom"}]},
    "quadrant": {"eyebrow": "Where to start", "title": "Pick automations by *impact and effort*",
                 "x": {"low": "Low effort", "high": "High effort"}, "y": {"low": "Low impact", "high": "High impact"},
                 "zones": {"tl": "Do first", "tr": "Plan it", "bl": "Quick fixes", "br": "Skip"},
                 "points": [{"label": "Tracking numbers", "x": 0.22, "y": 0.82, "us": True}, {"label": "Invoice OCR", "x": 0.7, "y": 0.78},
                            {"label": "Email sorting", "x": 0.3, "y": 0.35}, {"label": "Custom ERP", "x": 0.82, "y": 0.28}],
                 "win": "tl"},
    "code": {"eyebrow": "For technical founders", "title": "Keep secrets *out of the repo*", "filename": "settings.py", "language": "python",
             "code": "import os\n\n# Read keys from the environment,\n# never commit them to git.\nDB_URL = os.environ[\"DATABASE_URL\"]\nAPI_KEY = os.environ.get(\"API_KEY\")\n\nif API_KEY is None:\n    raise RuntimeError(\"API_KEY is not set\")",
             "caption": "The repo holds the code. Your vault holds the keys."},
    "terminal": {"eyebrow": "The handoff test", "title": "Can a new developer ship *alone*?", "filename": "handoff",
                 "lines": [{"cmd": "git clone org/your-app && cd your-app"}, {"cmd": "cp .env.example .env"},
                           {"cmd": "./scripts/deploy.sh", "out": "build ok - deployed to production"}, {"out": "If this works without a phone call, you own it."}]},
    "mockup": {"eyebrow": "Real work", "title": "An AI assistant *answering customers* on WhatsApp",
               "caption": "Built for CraftWorks in the UK. Their accounts, their code.", "url": "wizcodes.site/work/ai-whatsapp-automation",
               "project": "ai-whatsapp-automation",
               "app": {"name": "Noorly", "initials": "No", "category": "Productivity", "tech": ["Flutter", "Dart", "Firebase"]}},
    "cta": {"eyebrow": "Keep this", "headline": "Save *this.*", "sub": "Before you hire your next developer.",
            "ask": "What did your last developer keep?"},
    "recap": {"eyebrow": "The short version", "title": "Before you hire, *own these*",
              "items": ["The code repo", "The hosting account", "Every credential", "Written deploy steps"], "note": "Save this for your next build."},
}


def hostile(format_id: str) -> dict:
    """Every field at its limit - the case that decides whether a budget is real."""
    fmt = FORMATS[format_id]
    base = dict(GOOD.get(format_id, {}))

    def fill(spec: Field, seed_text: str, i: int = 0):
        if spec.kind == "text":
            words = ("Wide words test the layout like real copy does under pressure " * 20)
            return (seed_text + " " + words)[: spec.max].rstrip() if spec.max else seed_text
        if spec.kind == "num":
            return [0.2, 0.7, 0.4, 0.85, 0.3, 0.6][i % 6] if seed_text.lower() in ("x", "y") else (i + 1) * 7
        if spec.kind == "enum":
            return spec.choices[i % len(spec.choices)]
        if spec.kind == "bool":
            return i == 0
        if spec.kind == "list":
            return [fill(spec.item, f"Item {j + 1}", j) for j in range(spec.max)]
        if spec.kind == "obj":
            obj = {}
            for k, sub in (spec.fields or {}).items():
                if k == "icon":
                    obj[k] = "sparkles"
                elif k == "letter":
                    obj[k] = "ABCD"[i % 4]
                else:
                    v = fill(sub, k if sub.kind == "num" else f"{k.title()} {i + 1}", i)
                    if v is not None:
                        obj[k] = v
            return obj
        return None

    for name, spec in fmt.fields.items():
        if name in ("icon", "language", "kind", "winner", "win", "project", "ticker", "tree", "labels", "zones", "x", "y"):
            continue
        if format_id == "stat" and name == "value":
            base[name] = "99.9%"
            continue
        if format_id == "code" and name == "code":
            base[name] = "\n".join(f"line_{i:02d} = compute_value(data, key={i})"[:46] for i in range(12))
            continue
        val = fill(spec, name.title())
        if val is not None:
            base[name] = val
    if format_id == "chart":
        base["highlight"] = base["series"][0]["label"]
    return base
