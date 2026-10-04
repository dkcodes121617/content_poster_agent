"""The v2 writer: a prompt generated from the registry, a strict parser, and a
repair loop that fixes only what was rejected.

The deck's shape is decided by design/select.py before this runs. The writer
is told exactly which format each slide is, which fields that format takes and
how many characters each field can hold - generated from design/registry.py,
so the prompt can never describe a field the renderer does not have, or a
budget the validator does not enforce.

    draft, problems, attempts = prompt.write(client, system=..., user=..., plan=plan,
                                             snapshot=snapshot, gates=check_fn)

## Repair, not regeneration

The first real run regenerated whole decks on every rejection, and each fresh
draft fixed the flagged slide and broke a different one: five of ten decks
never converged. Now a rejected draft keeps everything that passed, and the
writer is asked for replacements of only the slides (or caption) that failed.
A whole-deck rewrite happens only when the draft could not be read at all.
"""
from __future__ import annotations

import json
import re

from design.registry import FORMATS, Field, budget, count_cap, validate
from design.select import DesignPlan
from prompts.library import (
    DIVISION_OF_LABOUR,
    PILLAR_BRIEFS,
    PLATFORM_BRIEFS,
    REGENERATE_NOTE,
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
    backticks, no links. Those characters reach the canvas literally.

A FACT KEEPS ITS EXACT MEANING ON A SLIDE. "26 projects delivered" never becomes
"26 projects delivered this way" or "26 projects, all started with a prototype":
the number is true, the claim attached to it is invented. Attach a number only
to what the facts say it counts. A quote is a real person's own words with
their own name and company exactly as the facts give them - never a project
or company they are not connected to."""

HOOK_RULES = """\
THE FIRST SLIDE (the hook) decides whether anything else is seen.

  - 4 to 9 words. It opens a loop the rest of the deck closes: a costly
    mistake, a surprising truth, a question with stakes, or a specific promise.
  - It is about the READER's situation, not about WizCodes.
  - Specific beats clever: "Your developer ghosted. Can you still deploy?"
    beats "The hidden risks of outsourcing".
  - No clickbait that the deck does not pay off, no "in this post", no
    "you won't believe", no question nobody would ask.
  - `sub` (optional) is one line saying what the swipe gets them.
  - A count in the hook or sub ("five signs") is a promise: the deck must
    contain exactly that many."""

GOAL_NOTES = {
    "saves": "This deck is built to be SAVED: make the middle slides a reference someone returns to.",
    "shares": "This deck is built to be SENT to a colleague: make it name a situation people recognise in someone else.",
    "comments": "This deck is built for COMMENTS: take a clear position a reasonable founder could disagree with.",
    "follows": "This deck is built to earn a FOLLOW: show a way of thinking the reader wants more of.",
    "clicks": "This deck is built to start a CONVERSATION about the free prototype, plainly.",
}

# What a layout changes about the words. Only where it changes something.
LAYOUT_NOTES = {
    ("vs", "columns"): "COLUMNS layout: fill left and right, each with a label and 2-4 points; leave rows out",
    ("vs", "table"): "TABLE layout: fill 3-5 rows (aspect, left, right) plus left.label and right.label; points are not shown",
    ("stat", "ring"): "RING layout: the value must be a percentage like '73%'",
    ("stat", "bento"): "BENTO layout: add 2-3 tiles of supporting figures from the facts",
    ("hook", "ticker"): "a one-word `ticker` runs huge behind the hook - choose the word that names the topic",
    ("hook", "split"): "the hook shares the slide with artwork - keep it to 6 words or fewer",
    ("timeline", "horizontal"): "HORIZONTAL layout: at most 3 events on a portrait canvas, short 'what' lines",
    ("mockup", "phone"): "PHONE layout: fill `app` (name, category, tech) from the project's own facts",
    ("mockup", "browser"): "BROWSER layout: `url` is the project's page, e.g. wizcodes.site/work/<slug>",
    ("checklist", "bento"): "BENTO layout: items are short (under 40 characters) and each gets an icon",
    ("cheat_sheet", "bento"): "BENTO layout: the first and last cells span the full width - make them the headline cells",
    ("decision_tree", "td"): "keep questions short: four answers sit side by side",
}

# Code and terminal text is shown character for character: a '#' starts a
# comment and '*' multiplies, so markup and emphasis checks do not apply.
_VERBATIM = {("code", "code"), ("terminal", "lines")}


def _shown(n: int) -> int:
    """The limit the writer is told: a little under the real one. A model
    given the exact limit treats it as a target and overshoots - the first
    real run missed by 1-7 characters in a third of its rejections."""
    return n if n <= 16 else int(n * 0.9)


# ── spec rendering ───────────────────────────────────────────────────────────


def _field_line(name: str, f: Field, indent: str = "      ", canvas: str = "portrait") -> list[str]:
    req = "required" if f.required else "optional"
    note = f" - {f.note}" if f.note else ""
    if f.kind == "text":
        return [f"{indent}{name}: text, {req}, max {_shown(budget(f.max, canvas))} characters{note}"]
    if f.kind == "num":
        return [f"{indent}{name}: number, {req}{note}"]
    if f.kind == "bool":
        return [f"{indent}{name}: true/false, {req}{note}"]
    if f.kind == "enum":
        return [f"{indent}{name}: one of {', '.join(f.choices)}, {req}{note}"]
    if f.kind == "tree":
        return [f"{indent}{name}: decision tree, {req}{note}",
                f"{indent}  shape: {{\"q\": \"question?\", \"yes\": <node or short leaf text>, \"no\": <node or leaf>}}",
                f"{indent}  questions max 43 characters, leaves max 36 characters"]
    if f.kind == "obj":
        out = [f"{indent}{name}: object, {req}{note}"]
        for k, sub in (f.fields or {}).items():
            out += _field_line(k, sub, indent + "    ", canvas)
        return out
    if f.kind == "list":
        hi = count_cap(f.max, f.min, canvas)
        span = f"{f.min}-{hi}" if f.min != hi else f"exactly {f.min}"
        item = f.item
        sub_fields = item if isinstance(item, dict) else (item.fields if isinstance(item, Field) and item.kind == "obj" else None)
        if sub_fields:
            out = [f"{indent}{name}: list of {span} objects, {req}{note}; each object:"]
            for k, sub in sub_fields.items():
                out += _field_line(k, sub, indent + "    ", canvas)
            return out
        if isinstance(item, Field) and item.kind == "text":
            return [f"{indent}{name}: list of {span} texts, each max {_shown(budget(item.max, canvas))} characters, {req}{note}"]
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
    first_seen: dict[tuple, int] = {}
    for i, s in enumerate(plan.slides, 1):
        fmt = FORMATS[s.format]
        key = (s.format, s.layout)
        layout_note = LAYOUT_NOTES.get(key)
        if key in first_seen:
            lines.append(f"  Slide {i}: {fmt.label} [{s.format}] - same fields as slide {first_seen[key]}, new content")
            lines.append("")
            continue
        first_seen[key] = i
        lines.append(f"  Slide {i}: {fmt.label} [{s.format}] - {fmt.good_for}")
        if layout_note:
            lines.append(f"      ({layout_note})")
        for name, f in fmt.fields.items():
            lines += _field_line(name, f, canvas=plan.canvas)
        if s.format == "cta":
            lines.append(f"      (this closer's buttons ask the reader to {s.layout}; the headline should make that the natural next step)")
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


REPAIR_NOTE = """\
YOUR DRAFT WAS CHECKED. Most of it passed and is kept exactly as it is:

{draft}

These parts were rejected:
{problems}

Fix only what was rejected. Return one JSON object containing only the
replacements, in this shape:
  {{"slides": [{{"index": <slide number>, "content": {{<the whole corrected content for that slide>}}}}],
   "caption": "<only if the caption was rejected>",
   "hashtags": ["<only if the hashtags were rejected>"]}}
Leave out every slide that was not rejected."""


# Rejections reworded as instructions. "Varies 17% around a 13-word average,
# wanted 18%" is true and unusable: four repairs in a row returned the same
# caption. "Is 79 characters - max 78" came back at 79. Say what to DO.
_OVER = re.compile(r"'([^']+)' is (\d+) characters - max (\d+)")


def _actionable(problem: str) -> str:
    m = _OVER.search(problem)
    if m:
        return _OVER.sub(f"'{m.group(1)}' is {m.group(2)} characters - rewrite it shorter, in at most "
                         f"{_shown(int(m.group(3)))} characters", problem)
    if "sentence lengths are too uniform" in problem:
        return ("caption: [voice] every sentence is about the same length, which reads as machine-written - rewrite "
                "the caption with one sentence of three to five words and one of twenty words or more")
    return problem


def repair(user_prompt: str, draft: dict, problems: list[str], repeated: set[str] | None = None) -> str:
    compact = {"caption": draft.get("caption", ""), "hashtags": draft.get("hashtags", []),
               "slides": [{"index": i, "format": s["format"], "content": s["content"]}
                          for i, s in enumerate(draft.get("slides") or [], 1)]}
    lines = []
    for p in problems[:16]:
        note = _actionable(p)
        if repeated and p in repeated:
            note += " (flagged again after the last fix - write this part completely differently)"
        lines.append(f"- {note}")
    return user_prompt + "\n\n" + REPAIR_NOTE.format(draft=json.dumps(compact, ensure_ascii=False), problems="\n".join(lines))


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


def parse(raw, plan: DesignPlan, snapshot=None) -> tuple[dict | None, list[str]]:
    """The draft and the reasons it cannot be used ([] when it can).

    `raw` is the model's text, or an already-parsed dict (a merged repair).
    Every slide problem starts "slide N", which is how repair() knows what to
    ask for again.
    """
    from wizcore.llm.client import extract_json

    data = raw if isinstance(raw, dict) else extract_json(raw)
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
            content = {}
        _fix_icons(content)
        if want.format == "mockup":
            _fill_app(content, snapshot)
        if want.format == "quadrant":
            _unit_points(content)
        problems += [f"slide {i} ({want.format}): {p}" for p in validate(want.format, content, want.layout, plan.canvas)]
        for where, text in _texts(content):
            if (want.format, where.split("[")[0].split(".")[0]) in _VERBATIM:
                continue
            for pattern, what in _MARKUP:
                if pattern.search(text):
                    problems.append(f"slide {i} {where} contains {what} - slides are plain text")
                    break
            if text.count("*") % 2 or text.count("==") % 2:
                problems.append(f"slide {i} {where} has an unclosed emphasis mark")
            if text.count("*") > 2:
                problems.append(f"slide {i} {where} marks more than one phrase - mark one")
        slides.append({"format": want.format, "layout": want.layout, "content": content})

    caption = str(data.get("caption") or "").strip()
    problems += grounded(slides, snapshot, caption=caption, pillar=plan.pillar)
    if not caption:
        problems.append("caption: it is empty")
    hashtags = [str(h).strip().lstrip("#") for h in (data.get("hashtags") or []) if str(h).strip()]
    draft = {"title": str(data.get("title") or "").strip()[:100], "caption": caption,
             "hashtags": hashtags, "slides": slides}
    return draft, problems


_WORD = re.compile(r"[a-z0-9']+")
_STOP = frozenset({"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "it", "is", "was", "were",
                   "be", "been", "are", "this", "that", "we", "our", "you", "your", "they", "their", "at", "by",
                   "from", "as", "so", "very", "really", "just"})


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(str(text).lower()) if w not in _STOP and len(w) > 2}


def _unit_points(content: dict) -> None:
    """Quadrant positions run 0 to 1, and writers often send 0-100 ("x": 90).
    The renderer clamped those into the far corner: every point of three real
    matrices landed in one spot with the labels stacked. A set written on a
    0-100 scale is rescaled rather than rejected - the intent is unambiguous."""
    pts = [p for p in content.get("points") or [] if isinstance(p, dict)]
    nums = [p[k] for p in pts for k in ("x", "y") if isinstance(p.get(k), (int, float)) and not isinstance(p.get(k), bool)]
    if nums and 1 < max(nums) <= 100 and min(nums) >= 0:
        for p in pts:
            for k in ("x", "y"):
                if isinstance(p.get(k), (int, float)) and not isinstance(p.get(k), bool):
                    p[k] = round(p[k] / 100, 3)


def _fill_app(content: dict, snapshot) -> None:
    """A phone mockup shows the app's identity, and the facts already have
    it: name, category and stack come from the project, never from the
    writer - the first real phone mockup left them out and drew "Ap" on an
    empty screen."""
    if snapshot is None:
        return
    project = next((p for p in getattr(snapshot, "projects", []) if p.slug and p.slug == content.get("project")), None)
    if project is None:
        return
    name = (project.name or "")[:24]
    initials = "".join(w[0] for w in name.split()[:2]).upper() or name[:2]
    content["app"] = {"name": name, "initials": initials[:2], "category": (project.category or "")[:24],
                      "tech": [str(t)[:14] for t in (project.tech or [])[:3]]}


# A figure from the facts with a claim bolted on: "26 projects delivered THIS
# WAY", "26 projects delivered WITH FIXED-SCOPE QUOTES", "ALL started with a
# prototype". The number is true; what it is said to count is invented. Real
# drafts did this three times, in a stat, a label and a recap footnote, with
# the writing rule in the prompt each time - so it is checked, everywhere.
_QUALIFIER = re.compile(r"\b(this way|all of them|all|every|each|always|without exception|started with|began with|"
                        r"with (?:a |an |our |the )?(?:free|working|fixed|prototype))", re.I)
# Words a label may add to the facts' own wording without changing the claim.
_LABEL_OK = {"wizcodes", "project", "projects", "delivered", "shipped", "built", "builds", "build", "live", "country",
             "countries", "client", "clients", "customer", "customers", "open", "source", "tools", "tool", "published",
             "endorsed", "endorsements", "publicly", "public", "work", "works", "apps", "products", "worldwide", "total",
             "so", "far", "to", "date", "across", "over", "served", "reached", "testimonials", "reviews"}


def _stat_facts(snapshot) -> dict[str, str]:
    """Our own figures and what each one counts: {"26": "projects delivered"}."""
    try:
        return {str(s["value"]): str(s.get("label") or "") for s in (snapshot.chartable_stats() or [])
                if s.get("scope", "ours") == "ours"}
    except Exception:
        return {}


def _num_key(v) -> str:
    """26, 26.0 and "26" are the same figure; 10 must not become "1"."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(f)) if f.is_integer() else str(f)


def _stem(words: set[str]) -> set[str]:
    return {w[:-1] if w.endswith("s") and len(w) > 3 else w for w in words}


def _figure_claims(where: str, text: str, facts: dict[str, str]) -> list[str]:
    """A figure of ours followed, within a few words, by a qualifier - but only
    when those words are about what the figure counts: "5 questions every
    quote should answer" is not our 5 open-source tools."""
    out = []
    for m in re.finditer(r"(?<![\d.,])(\d+)(?![\d.,%])", text):
        if m.group(1) not in facts:
            continue
        after = " ".join(text[m.end():].split()[:9])
        if not _stem(_words(" ".join(after.split()[:4]))) & _stem(_words(facts[m.group(1)])):
            continue
        q = _QUALIFIER.search(after)
        if q:
            out.append(f"{where}: '{m.group(1)} ... {q.group(0)}' claims more than the facts - they say {m.group(1)} "
                       f"counts '{facts[m.group(1)]}', and nothing about how or with what")
    return out


def grounded(slides: list[dict], snapshot, caption: str = "", pillar: str = "") -> list[str]:
    """Claims the slides make by STRUCTURE, which the prose gate cannot see:
    a mockup naming a project, a quote naming a person, a role, their words."""
    if snapshot is None:
        return []
    problems: list[str] = []
    slugs = {p.slug for p in getattr(snapshot, "projects", []) if p.slug}
    testimonials = list(getattr(snapshot, "testimonials", []))
    facts = _stat_facts(snapshot)
    known = set(facts) | {str(n) for n in (snapshot.known_numbers() if hasattr(snapshot, "known_numbers") else set())}
    if caption:
        problems += _figure_claims("caption", caption, facts)
    for i, s in enumerate(slides, 1):
        c = s.get("content") or {}
        for where, text in _texts(c):
            problems += _figure_claims(f"slide {i} {where}", text, facts)
        value = str(c.get("value", "")).strip()
        if s["format"] == "stat" and value in facts:
            extra = _words(c.get("label", "")) - _words(facts[value]) - _LABEL_OK
            if extra:
                problems.append(f"slide {i}: the label adds '{' '.join(sorted(extra))}' to {value} - the facts count "
                                f"'{facts[value]}'; say that, in those words or fewer")
        if s["format"] == "chart" and pillar != "timely":
            # Only the curated figures: "1, 2, 3" also occur somewhere in the
            # facts, and a chart of 1-2-3-4 "scores" is a chart of nothing.
            fake = [_num_key(it.get("value")) for it in (c.get("series") or []) if isinstance(it, dict)
                    and _num_key(it.get("value")) not in facts]
            if fake:
                problems.append(f"slide {i}: the chart plots {', '.join(fake[:3])}, which the facts do not contain - "
                                f"chart only real figures ({', '.join(f'{v} {lbl}' for v, lbl in facts.items())})")
        if s["format"] == "mockup" and c.get("project") and c["project"] not in slugs:
            problems.append(f"slide {i}: project '{c['project']}' is not a WizCodes project slug - use one from the facts")
        if s["format"] != "quote":
            continue
        name = str(c.get("name") or "").strip()
        if not name or "wizcodes" in name.lower():
            continue                                   # the studio's own principle
        named = [t for t in testimonials if t.name and re.search(rf"\b{re.escape(t.name.lower())}\b", name.lower())]
        if not named:
            problems.append(f"slide {i}: '{name}' is not a testimonial in the facts - quote a real client by the name the facts give, or attribute the line to WizCodes")
            continue
        quote = _words(c.get("quote", ""))
        best = max(named, key=lambda t: len(quote & _words(t.text)))
        if quote and len(quote & _words(best.text)) / len(quote) < 0.6:
            problems.append(f"slide {i}: the quote is not {best.name}'s own words - use their testimonial text, trimmed")
        role = _words(c.get("role", ""))
        known = _words(" ".join(str(getattr(best, k, "") or "") for k in ("role", "company", "country", "platform")))
        if role - known - {"client", "founder", "customer"}:
            problems.append(f"slide {i}: the role '{c.get('role')}' is not in {best.name}'s testimonial - use their company "
                            f"or role as the facts give it, or leave it out")
    return problems


# ── the loop ─────────────────────────────────────────────────────────────────

_SLIDE = re.compile(r"^slide (\d+)\b")


def write(client, *, system: str, user: str, plan: DesignPlan, snapshot=None, gates=None,
          max_calls: int = 4, max_tokens: int = 8000, temperature: float = 0.75,
          on_attempt=None) -> tuple[dict | None, list[str], list[dict]]:
    """Draft a deck, check it, and repair what fails.

    `gates(draft) -> problems` runs the prose gates (grounding, claims, voice,
    platform...) and should prefix slide-specific problems "slide N:" and
    caption problems "caption:" so the repair can target them.
    Returns (draft, remaining problems, attempts).
    """
    import time

    attempts: list[dict] = []
    draft, problems = None, ["not attempted"]
    prompt_text, mode = user, "draft"
    for call in range(1, max_calls + 1):
        t0 = time.time()
        try:
            raw = client.complete(system=system, user=prompt_text, max_tokens=max_tokens, temperature=temperature)
        except Exception as e:  # recorded, never raised: one failed call must not end a run
            problems = [f"generation failed: {e}"]
            attempts.append({"call": call, "mode": "error", "seconds": round(time.time() - t0, 1), "problems": problems})
            break
        if mode == "repair":
            draft, problems = _merge(draft, raw, plan, snapshot)
        else:
            draft, problems = parse(raw, plan, snapshot)
        if draft is not None and not problems and gates:
            problems = gates(draft)
        attempts.append({"call": call, "mode": mode, "seconds": round(time.time() - t0, 1), "problems": list(problems)})
        if on_attempt:
            on_attempt(attempts[-1])
        if draft is not None and not problems:
            break
        targeted = draft is not None and all(_SLIDE.match(p) or p.startswith("caption") for p in problems)
        if targeted:
            seen = {p for a in attempts[:-1] for p in a["problems"]}
            prompt_text, mode = repair(user, draft, problems, repeated=seen & set(problems)), "repair"
        else:
            draft, mode = None, "draft"
            prompt_text = user + "\n\n" + REGENERATE_NOTE.format(reasons="\n".join(f"- {p}" for p in problems[:12]))
    return draft, problems, attempts


def _merge(draft: dict, raw: str, plan: DesignPlan, snapshot) -> tuple[dict | None, list[str]]:
    """Apply a repair's replacements to the kept draft, then check it whole."""
    from wizcore.llm.client import extract_json

    data = extract_json(raw)
    if not isinstance(data, dict):
        return draft, ["Return one JSON object with the replacements, nothing before or after it."]
    slides = [{"format": s["format"], "content": s["content"]} for s in draft["slides"]]
    for rep in data.get("slides") or []:
        try:
            idx = int(rep.get("index")) - 1
        except (TypeError, ValueError, AttributeError):
            continue
        if 0 <= idx < len(slides) and isinstance(rep.get("content"), dict):
            slides[idx]["content"] = rep["content"]
    merged = {"title": draft.get("title", ""),
              "caption": data.get("caption") or draft.get("caption", ""),
              "hashtags": data.get("hashtags") or draft.get("hashtags", []),
              "slides": slides}
    return parse(merged, plan, snapshot)


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
