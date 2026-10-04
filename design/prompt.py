"""The v2 writer: a prompt generated from the registry, and a strict parser.

The deck's shape is decided by design/select.py before this runs. The writer
is told exactly which format each slide is, which fields that format takes and
how many characters each field can hold - generated from design/registry.py,
so the prompt can never describe a field the renderer does not have, or a
budget the validator does not enforce.

    system = prompt.system(facts_block, stats_block)
    user   = prompt.user(plan, platform=..., pillar=..., extra=..., ...)
    draft, problems = prompt.parse(raw, plan, snapshot)

`problems` are worded as regeneration notes: the write loop feeds them back
and asks again, which fixes most of them on the second attempt.
"""
from __future__ import annotations

import json
import re

from design.registry import FORMATS, Field, validate
from design.select import DesignPlan
from prompts.library import (
    DIVISION_OF_LABOUR,
    PILLAR_BRIEFS,
    PLATFORM_BRIEFS,
    post_system_prompt,
)

# Icons the writer may name. A curated slice of the 1,866 in the sprite: the
# ones that mean something in posts about building software for a business.
ICONS = (
    "rocket", "zap", "shield-check", "lock", "key-round", "git-branch", "github", "database", "server", "cloud",
    "code", "terminal", "bug", "wrench", "settings", "cpu", "bot", "brain", "sparkles", "workflow",
    "message-circle", "mail", "phone", "calendar-check", "clock", "timer", "file-text", "clipboard-check", "list-checks",
    "check", "circle-check", "circle-x", "triangle-alert", "flag", "eye", "search", "target", "trending-up", "chart-bar",
    "layers", "layout-dashboard", "smartphone", "globe", "credit-card", "receipt", "users", "user-check", "handshake",
    "lightbulb", "compass", "map", "puzzle", "repeat", "refresh-cw", "arrow-right-left", "scale", "gauge", "box",
    "package", "store", "shopping-cart", "headphones", "mic", "image", "pen-tool", "palette", "book-open", "graduation-cap",
)

DESIGN_RULES = """\
HOW TO WRITE FOR SLIDES

Each slide is set in large type on a designed canvas. The words ARE the design,
so write them the way a good designer would want them:

  - Short beats complete. A slide is read in two seconds; a fragment that lands
    beats a sentence that explains. Cut every word the slide survives without.
  - One idea per slide, and every slide must make sense on its own as a
    screenshot - people save and send single slides.
  - Concrete nouns over abstractions: "the repo, the hosting, the passwords"
    beats "your technical assets".
  - Parallel structure in lists: every item starts the same way (all verbs, or
    all nouns) and is roughly the same length.
  - Mark ONE phrase per heading with *asterisks* - the template sets it in the
    accent colour. Never more than one per field, never a whole sentence.
    ==double equals== draws a highlighter instead; use it at most once a deck.
  - Plain text otherwise: no markdown, no bullets, no emoji, no HTML, no
    backticks, no links. Those characters reach the canvas literally."""

HOOK_RULES = """\
THE FIRST SLIDE (the hook) decides whether anything else is seen.

  - 4 to 9 words. It opens a loop the rest of the deck closes: a costly
    mistake, a surprising truth, a question with stakes, or a specific promise.
  - It is about the READER's situation, not about WizCodes.
  - Specific beats clever: "Your developer ghosted. Can you still deploy?"
    beats "The hidden risks of outsourcing".
  - No clickbait that the deck does not pay off, no "in this post", no
    "you won't believe", no question nobody would ask.
  - `sub` (optional) is one line saying what the swipe gets them."""

GOAL_NOTES = {
    "saves": "This deck is built to be SAVED: make the middle slides a reference someone returns to.",
    "shares": "This deck is built to be SENT to a colleague: make it name a situation people recognise in someone else.",
    "comments": "This deck is built for COMMENTS: take a clear position a reasonable founder could disagree with.",
    "follows": "This deck is built to earn a FOLLOW: show a way of thinking the reader wants more of.",
    "clicks": "This deck is built to start a CONVERSATION about the free prototype, plainly.",
}


# ── spec rendering ───────────────────────────────────────────────────────────


def _field_line(name: str, f: Field, indent: str = "      ") -> list[str]:
    req = "required" if f.required else "optional"
    note = f" - {f.note}" if f.note else ""
    if f.kind == "text":
        return [f"{indent}{name}: text, {req}, max {f.max} characters{note}"]
    if f.kind == "num":
        return [f"{indent}{name}: number, {req}{note}"]
    if f.kind == "bool":
        return [f"{indent}{name}: true/false, {req}{note}"]
    if f.kind == "enum":
        return [f"{indent}{name}: one of {', '.join(f.choices)}, {req}{note}"]
    if f.kind == "tree":
        return [f"{indent}{name}: decision tree, {req}{note}",
                f"{indent}  shape: {{\"q\": \"question?\", \"yes\": <node or short leaf text>, \"no\": <node or leaf>}}",
                f"{indent}  questions max 48 characters, leaves max 40 characters"]
    if f.kind == "obj":
        out = [f"{indent}{name}: object, {req}{note}"]
        for k, sub in (f.fields or {}).items():
            out += _field_line(k, sub, indent + "    ")
        return out
    if f.kind == "list":
        span = f"{f.min}-{f.max}" if f.min != f.max else f"exactly {f.min}"
        item = f.item
        sub_fields = item if isinstance(item, dict) else (item.fields if isinstance(item, Field) and item.kind == "obj" else None)
        if sub_fields:
            out = [f"{indent}{name}: list of {span} objects, {req}{note}; each object:"]
            for k, sub in sub_fields.items():
                out += _field_line(k, sub, indent + "    ")
            return out
        if isinstance(item, Field) and item.kind == "text":
            return [f"{indent}{name}: list of {span} texts, each max {item.max} characters, {req}{note}"]
        return [f"{indent}{name}: list of {span}, {req}{note}"]
    return [f"{indent}{name}: {f.kind}, {req}{note}"]


def _example_value(f: Field):
    if f.kind == "text":
        return "..."
    if f.kind == "num":
        return 0
    if f.kind == "bool":
        return False
    if f.kind == "enum":
        return f.choices[0]
    if f.kind == "tree":
        return {"q": "...?", "yes": "...", "no": {"q": "...?", "yes": "...", "no": "..."}}
    if f.kind == "obj":
        return {k: _example_value(v) for k, v in (f.fields or {}).items() if v.required}
    if f.kind == "list":
        n = max(1, min(2, f.max or 2))
        if isinstance(f.item, dict):
            one = {k: _example_value(v) for k, v in f.item.items() if v.required}
        elif isinstance(f.item, Field):
            one = _example_value(f.item)
        else:
            one = "..."
        return [one] * n
    return "..."


def deck_spec(plan: DesignPlan) -> str:
    """The exact deck to write, slide by slide, from the registry."""
    lines = [(f"THE DECK: {len(plan.slides)} slide{'s' if len(plan.slides) != 1 else ''}, in this order. "
              "Each slide's format is fixed - write the words for it, not a different structure."), ""]
    first_seen: dict[str, int] = {}
    for i, s in enumerate(plan.slides, 1):
        fmt = FORMATS[s.format]
        if s.format in first_seen:
            lines.append(f"  Slide {i}: {fmt.label} [{s.format}] - same fields as slide {first_seen[s.format]}, new content")
            lines.append("")
            continue
        first_seen[s.format] = i
        lines.append(f"  Slide {i}: {fmt.label} [{s.format}] - {fmt.good_for}")
        for name, f in fmt.fields.items():
            lines += _field_line(name, f)
        if s.format == "cta":
            lines.append(f"      (this closer's buttons ask the reader to {s.layout}; the headline should make that the natural next step)")
        if s.format == "stat" and s.layout == "ring":
            lines.append("      (this layout draws a ring: the value must be a percentage like '73%')")
        if s.format == "mockup":
            lines.append("      (project must be the slug of a real project in the facts; for the phone layout fill `app` from that project)")
        lines.append("")
    example = {"title": "...", "caption": "...", "hashtags": ["..."],
               "slides": [{"format": s.format, "content": {k: _example_value(f) for k, f in FORMATS[s.format].fields.items() if f.required}}
                          for s in plan.slides]}
    lines.append("Return one JSON object shaped like this (the '...' are yours to write; optional fields may be added):")
    lines.append(json.dumps(example, ensure_ascii=False))
    lines.append("")
    lines.append("Character limits are hard limits: an over-long field is rejected, not shrunk.")
    if any(_mentions_icons(FORMATS[s.format]) for s in plan.slides):
        lines.append("Icon fields take one of: " + ", ".join(ICONS) + ".")
    return "\n".join(lines)


def _mentions_icons(fmt) -> bool:
    def walk(f) -> bool:
        if isinstance(f, dict):
            return any(k == "icon" or walk(v) for k, v in f.items())
        if isinstance(f, Field):
            return walk(f.fields or {}) or walk(f.item) if f.item is not None else walk(f.fields or {})
        return False
    return walk(fmt.fields)


# ── prompts ──────────────────────────────────────────────────────────────────


def system(facts_block: str, stats_block: str = "") -> str:
    return post_system_prompt(facts_block, stats_block) + "\n\n" + DESIGN_RULES


def user(plan: DesignPlan, *, platform: str, pillar: str, extra: str = "",
         region_brief: str = "", phrase_brief: str = "") -> str:
    lines = [
        f"Write one {platform} post.",
        "",
        f"Pillar: {pillar}. {PILLAR_BRIEFS.get(pillar, '')}",
        f"Platform: {PLATFORM_BRIEFS.get(platform, '')}",
        f"The deck's angle: {plan.feels_like}.",
        GOAL_NOTES.get(plan.goal, ""),
    ]
    if region_brief:
        lines += ["", region_brief]
    if phrase_brief:
        lines += ["", phrase_brief]
    if extra:
        lines += ["", extra]
    if plan.slides and plan.slides[0].format == "hook":
        lines += ["", HOOK_RULES]
    lines += ["", deck_spec(plan), "", DIVISION_OF_LABOUR, "",
              "`title` is a plain title for the post under 100 characters (LinkedIn shows it on the document).",
              "Return the JSON object on its own, with nothing before or after it."]
    return "\n".join(x for x in lines if x is not None)


# ── parsing ──────────────────────────────────────────────────────────────────

_MARKUP = (
    (re.compile(r"`"), "a backtick"),
    (re.compile(r"!?\[[^\]]*\]\([^)]*\)"), "a markdown link"),
    (re.compile(r"^\s{0,3}#{1,6}\s", re.M), "a markdown heading"),
    (re.compile(r"^\s*[-+•]\s+", re.M), "a bullet character"),
    (re.compile(r"<[a-zA-Z/][^>]*>"), "an HTML tag"),
    (re.compile(r"https?://"), "a URL"),
    (re.compile(r"\\n|\\t"), "an escaped newline written as two characters"),
)


def _texts(value, path: str = ""):
    """Every (path, text) leaf in a content dict."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for k, v in value.items():
            if k in ("icon", "language", "from", "tier", "winner", "win", "kind"):
                continue
            yield from _texts(v, f"{path}.{k}" if path else k)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _texts(v, f"{path}[{i}]")


def _fix_icons(value) -> None:
    """Unknown icon names become a neutral one instead of a regeneration."""
    from design.render import icon_names

    known = set(icon_names())

    def walk(v):
        if isinstance(v, dict):
            for k, val in v.items():
                if k == "icon" and isinstance(val, str) and val not in known:
                    v[k] = "sparkles"
                else:
                    walk(val)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(value)


def parse(raw: str, plan: DesignPlan, snapshot=None) -> tuple[dict | None, list[str]]:
    """The draft and the reasons it cannot be used ([] when it can)."""
    from wizcore.llm.client import extract_json

    data = extract_json(raw)
    if not isinstance(data, dict):
        return None, ["Return one JSON object, with nothing before or after it."]
    problems: list[str] = []
    slides_in = data.get("slides")
    if not isinstance(slides_in, list):
        return None, ["'slides' must be a list with one entry per slide."]
    if len(slides_in) != len(plan.slides):
        problems.append(f"the deck has {len(plan.slides)} slides; the draft has {len(slides_in)} - write exactly one per slide, in order")

    slides: list[dict] = []
    for i, want in enumerate(plan.slides, 1):
        got = slides_in[i - 1] if i - 1 < len(slides_in) else None
        content = got.get("content") if isinstance(got, dict) else None
        if isinstance(got, dict) and got.get("format") not in (None, want.format):
            problems.append(f"slide {i} must be a {want.format}, not {got.get('format')}")
        if not isinstance(content, dict):
            problems.append(f"slide {i} ({want.format}) needs a 'content' object")
            continue
        _fix_icons(content)
        problems += [f"slide {i} ({want.format}): {p}" for p in validate(want.format, content)]
        for where, text in _texts(content):
            for pattern, what in _MARKUP:
                if pattern.search(text):
                    problems.append(f"slide {i} {where} contains {what} - slides are plain text")
                    break
            if text.count("*") % 2 or text.count("==") % 2:
                problems.append(f"slide {i} {where} has an unclosed emphasis mark")
            if text.count("*") > 2:
                problems.append(f"slide {i} {where} marks more than one phrase - mark one")
        slides.append({"format": want.format, "layout": want.layout, "content": content})

    problems += grounded(slides, snapshot)
    caption = str(data.get("caption") or "").strip()
    if not caption:
        problems.append("'caption' is empty")
    hashtags = [str(h).strip().lstrip("#") for h in (data.get("hashtags") or []) if str(h).strip()]
    draft = {"title": str(data.get("title") or "").strip()[:100], "caption": caption,
             "hashtags": hashtags, "slides": slides}
    return draft, problems


def grounded(slides: list[dict], snapshot) -> list[str]:
    """Claims the slides make by STRUCTURE, which the prose gate cannot see:
    a mockup naming a project, a quote naming a person."""
    if snapshot is None:
        return []
    problems: list[str] = []
    slugs = {p.slug for p in getattr(snapshot, "projects", []) if p.slug}
    people = {t.name.strip().lower() for t in getattr(snapshot, "testimonials", []) if t.name}
    for i, s in enumerate(slides, 1):
        c = s.get("content") or {}
        if s["format"] == "mockup" and c.get("project") and c["project"] not in slugs:
            problems.append(f"slide {i}: project '{c['project']}' is not a WizCodes project slug - use one from the facts")
        if s["format"] == "quote":
            name = str(c.get("name") or "").strip().lower()
            if name and name not in people and "wizcodes" not in name:
                problems.append(f"slide {i}: '{c.get('name')}' is not a testimonial in the facts - quote a real client or attribute the line to WizCodes")
    return problems


# ── text for the prose gates ─────────────────────────────────────────────────


def visible_text(slides: list[dict]) -> str:
    """Everything a reader can see on the slides, plus engine data written out
    as sentences, so the grounding and claims gates read the chart's numbers
    the same way they read prose: a bar is just a number in a bigger font."""
    parts: list[str] = []
    for s in slides:
        c = s.get("content") or {}
        parts += [t.replace("*", "").replace("==", "") for _, t in _texts(c)]
        if s.get("format") == "chart":
            unit = str(c.get("unit") or "")
            for item in c.get("series") or []:
                if isinstance(item, dict):
                    parts.append(f"{item.get('label', '')}: {item.get('value', '')}{(' ' + unit) if unit else ''}.")
    return " ".join(p for p in parts if p)
