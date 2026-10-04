"""The design engine's vocabulary — formats, looks, art, accents, canvases.

One registry is read by three consumers, which is the point of it:

  * the WRITER prompt   (design/prompt.py renders each format's fields and
                         budgets from here, so the model is told exactly what
                         the renderer can hold)
  * the VALIDATOR       (validate() below rejects a spec before it reaches a
                         browser: missing fields, over-budget text, wrong item
                         counts)
  * the RENDERER        (engines a format needs, the layouts it may use)

A format and a look are independent axes: any format can wear any look, and
the selector (design/select.py) rotates both. Budgets are in characters and
were set by rendering the hostile fixtures in design/fixtures.py at their limit
in every look — a budget is a measurement, not a guess.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ── fields ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Field:
    kind: str                      # text | list | obj | num | enum | tree | bool
    required: bool = True
    max: int = 0                   # chars (text) or items (list)
    min: int = 0                   # items (list)
    item: object = None            # list item: a Field, or a dict of Fields
    fields: dict | None = None     # obj
    choices: tuple = ()
    note: str = ""


def T(max_chars: int, required: bool = True, note: str = "") -> Field:
    return Field("text", required=required, max=max_chars, note=note)


def L(item, lo: int, hi: int, required: bool = True, note: str = "") -> Field:
    return Field("list", required=required, min=lo, max=hi, item=item, note=note)


def Obj(fields: dict, required: bool = True, note: str = "") -> Field:
    return Field("obj", required=required, fields=fields, note=note)


def E(*choices: str, required: bool = True, note: str = "") -> Field:
    return Field("enum", required=required, choices=tuple(choices), note=note)


EYEBROW = T(32, required=False, note="tiny label above the content, e.g. 'Before you hire'")

# ── formats ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Format:
    id: str
    label: str
    family: str                    # single | slide | both  (slide = carousel-only)
    layouts: tuple
    fields: dict
    good_for: str
    engines: tuple = ()
    pillars: tuple = ("teach", "proof", "pov", "process", "timely")
    landscape_ok: bool = True      # survives a 16:9 canvas (X)
    needs_svg: bool = False        # takes real project artwork


FORMATS: dict[str, Format] = {f.id: f for f in [
    Format("hook", "Hook / cover", "slide", ("stack", "split", "center", "ticker"),
           {"eyebrow": EYEBROW, "hook": T(70, note="the scroll-stopper, 4-9 words, mark ONE key phrase *like this*"),
            "sub": T(110, required=False), "ticker": T(14, required=False, note="one word for the ticker band")},
           "the first slide of a carousel: a tension, mistake or promise the reader feels"),
    Format("hot_take", "Hot take", "both", ("big", "quote", "underline"),
           {"eyebrow": EYEBROW, "take": T(78, note="one opinionated sentence; mark ONE phrase *like this*"),
            "support": T(110, required=False)},
           "a sharp opinion people will agree or argue with", pillars=("pov", "timely")),
    Format("stat", "Big number", "both", ("hero", "ring", "bento"),
           {"eyebrow": EYEBROW, "value": T(8, note="the number exactly as shown, e.g. '<200ms', '11', '73%'"),
            "label": T(70), "context": T(130, required=False), "source": T(60, note="always: the project for our own figures, e.g. 'CuePilot, a WizCodes build'; the publisher for an external one"),
            "tiles": L(Obj({"value": T(8), "label": T(36)}), 0, 3, required=False), "icon": T(24, required=False)},
           "one number that makes the point; ring layout only for a percentage", pillars=("proof", "timely", "teach")),
    Format("chart", "Chart", "both", ("bar", "column", "donut"),
           {"eyebrow": EYEBROW, "title": T(70), "series": L(Obj({"label": T(22), "value": Field("num")}), 2, 6),
            "unit": T(10, required=False), "highlight": T(22, required=False, note="label of the bar to emphasise"),
            "source": T(60, note="always: 'wizcodes.site' for our own figures; the publisher for an external one")},
           "a comparison of 2-6 real numbers", engines=("vega",), pillars=("proof", "timely", "teach")),
    Format("quote", "Quote", "both", ("classic", "card"),
           {"eyebrow": EYEBROW, "quote": T(170, note="a real testimonial's own words, trimmed - or a WizCodes principle"),
            "name": T(40, note="the person exactly as named in the testimonials, or 'WizCodes'"),
            "role": T(50, required=False, note="their company or role, from the facts")},
           "a real client testimonial or the studio's own principle", pillars=("proof", "pov")),
    Format("myth_fact", "Myth vs reality", "both", ("stacked", "split"),
           {"eyebrow": EYEBROW, "title": T(50, required=False), "myth": T(100), "fact": T(130, note="mark ONE phrase *like this*")},
           "correcting a belief buyers commonly hold", pillars=("teach", "pov")),
    Format("post_card", "Post card", "single", ("card",),
           {"text": T(230, note="a punchy post in the studio voice; line breaks allowed"),
            "name": T(30, required=False), "handle": T(24, required=False)},
           "a short opinion styled as a social post screenshot", pillars=("pov", "timely")),
    Format("notes", "Notes app", "both", ("ios",),
           {"title": T(48), "date": T(24, required=False), "items": L(Obj({"text": T(70), "done": Field("bool", required=False)}), 3, 7)},
           "a candid list, like a founder's notes", pillars=("teach", "process", "pov")),
    Format("chat", "Chat", "both", ("bubbles",),
           {"eyebrow": EYEBROW, "title": T(54, required=False),
            "messages": L(Obj({"from": E("them", "us"), "text": T(68)}), 3, 4),
            "labels": Obj({"them": T(16, required=False), "us": T(16, required=False)}, required=False)},
           "a typical exchange with a client that teaches something", pillars=("teach", "process", "pov")),
    Format("checklist", "Checklist", "both", ("list", "cards", "bento"),
           {"eyebrow": EYEBROW, "title": T(64), "items": L(Obj({"text": T(50), "sub": T(56, required=False), "icon": T(24, required=False)}), 3, 5),
            "kind": E("do", "dont", required=False), "note": T(90, required=False)},
           "a save-worthy list the reader can act on", pillars=("teach", "process")),
    Format("cheat_sheet", "Cheat sheet", "both", ("grid", "bento", "numbered"),
           {"eyebrow": EYEBROW, "title": T(54), "cells": L(Obj({"head": T(18), "body": T(54), "icon": T(24, required=False)}), 4, 6)},
           "a dense reference people save and share", pillars=("teach",), landscape_ok=False),
    Format("flags", "Red / green flags", "both", ("columns",),
           {"eyebrow": EYEBROW, "title": T(54, required=False), "red": L(T(44), 2, 4), "green": L(T(44), 2, 4),
            "red_label": T(16, required=False), "green_label": T(16, required=False)},
           "signs of a good or bad partner/process", pillars=("teach", "pov")),
    Format("vs", "This vs that", "both", ("columns", "table"),
           {"eyebrow": EYEBROW, "title": T(56, required=False),
            "left": Obj({"label": T(22), "points": L(T(52), 2, 4, required=False, note="columns layout")}),
            "right": Obj({"label": T(22), "points": L(T(52), 2, 4, required=False, note="columns layout")}),
            "rows": L(Obj({"aspect": T(22), "left": T(40), "right": T(40)}), 3, 5, required=False, note="table layout only"),
            "winner": E("left", "right", required=False), "verdict": T(110, required=False)},
           "an honest comparison of two options", pillars=("teach", "pov")),
    Format("steps", "Steps", "both", ("rail", "cards"),
           {"eyebrow": EYEBROW, "title": T(60), "steps": L(Obj({"head": T(36), "body": T(64, required=False)}), 3, 5)},
           "a process in order (never with durations)", pillars=("process", "teach")),
    Format("framework", "Framework", "both", ("pillars", "acronym"),
           {"eyebrow": EYEBROW, "name": T(22, required=False), "title": T(58, required=False),
            "pillars": L(Obj({"letter": T(1, required=False), "head": T(26), "body": T(76, required=False)}), 3, 4)},
           "a named mental model with 3-4 parts", pillars=("teach", "pov")),
    Format("tier_list", "Tier list", "both", ("tiers",),
           {"eyebrow": EYEBROW, "title": T(56), "tiers": L(Obj({"tier": E("S", "A", "B", "C", "D"), "items": L(T(22), 1, 2)}), 3, 4)},
           "ranking approaches/practices (never named competitors)", pillars=("pov", "teach")),
    Format("iceberg", "Iceberg", "both", ("iceberg",),
           {"eyebrow": EYEBROW, "title": T(56), "above": L(T(26), 2, 3), "below": L(T(30), 3, 6),
            "above_label": T(20, required=False), "below_label": T(20, required=False)},
           "what people see vs what it actually takes", pillars=("teach", "process"), landscape_ok=False),
    Format("poll", "Poll", "single", ("options",),
           {"eyebrow": EYEBROW, "question": T(90), "options": L(T(44), 2, 4), "ask": T(60, required=False)},
           "a question that invites comments", pillars=("pov", "teach")),
    Format("decision_tree", "Decision tree", "both", ("td", "lr"),
           {"eyebrow": EYEBROW, "title": T(60),
            "tree": Field("tree", note="{q, yes, no} where yes/no is another node or a short leaf string; max depth 3, max 9 boxes")},
           "a yes/no decision a buyer faces", engines=("mermaid",), pillars=("teach",)),
    Format("timeline", "Timeline", "both", ("vertical", "horizontal"),
           {"eyebrow": EYEBROW, "title": T(58), "events": L(Obj({"when": T(16, note="a stage ('The problem', 'Prototype', 'Today') or a real date from the facts - never a week number or a duration"),
                              "what": T(64)}), 3, 5)},
           "how something evolved (milestones, history) - never a delivery schedule", pillars=("process", "timely", "proof")),
    Format("quadrant", "2x2 matrix", "both", ("matrix",),
           {"eyebrow": EYEBROW, "title": T(56),
            "x": Obj({"low": T(16), "high": T(16)}), "y": Obj({"low": T(16), "high": T(16)}),
            "zones": Obj({"tl": T(18, required=False), "tr": T(18, required=False), "bl": T(18, required=False), "br": T(18, required=False)}, required=False),
            "points": L(Obj({"label": T(20), "x": Field("num", note="0 (left) to 1 (right)"),
                             "y": Field("num", note="0 (bottom) to 1 (top)"), "us": Field("bool", required=False)}), 2, 6),
            "win": E("tl", "tr", "bl", "br", required=False)},
           "positioning options on two axes", pillars=("teach", "pov")),
    Format("code", "Code card", "both", ("editor",),
           {"eyebrow": EYEBROW, "title": T(56, required=False), "filename": T(28, required=False),
            "language": E("python", "typescript", "javascript", "bash", "json", "sql"),
            "code": T(520, note="max 12 lines x 46 columns"), "caption": T(100, required=False)},
           "a small, real code idea for technical founders", engines=("prism",), pillars=("teach",), landscape_ok=False),
    Format("terminal", "Terminal", "both", ("session",),
           {"eyebrow": EYEBROW, "title": T(56, required=False), "filename": T(20, required=False),
            "lines": L(Obj({"cmd": T(46, required=False), "out": T(90, required=False)}), 2, 6)},
           "a command-line moment that makes a point", pillars=("teach",), landscape_ok=False),
    Format("mockup", "Project mockup", "both", ("browser", "phone"),
           {"eyebrow": EYEBROW, "title": T(60), "caption": T(110, required=False), "url": T(48, required=False),
            "project": T(60, note="slug of a REAL WizCodes project with artwork"),
            "app": Obj({"name": T(24), "initials": T(2, required=False), "category": T(24, required=False),
                        "tech": L(T(14), 0, 3, required=False)}, required=False, note="phone layout: the real app's name, category, tech")},
           "showing real work", pillars=("proof",), needs_svg=True),
    Format("cta", "Call to action", "slide", ("save", "follow", "comment"),
           {"eyebrow": EYEBROW, "headline": T(44, note="mark ONE word *like this*"), "sub": T(90, required=False), "ask": T(90, required=False)},
           "the last slide of a carousel: ask for a save, share or comment"),
    Format("recap", "Recap", "slide", ("checklist",),
           {"eyebrow": EYEBROW, "title": T(54), "items": L(T(52), 3, 6), "note": T(70, required=False)},
           "the summary slide people screenshot - repeats the carousel's key points"),
]}

# ── looks ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Look:
    id: str
    tone: str                      # dark | light
    moods: tuple
    art: tuple                     # art kinds that suit it
    places: tuple = ("bg", "corner", "band")
    avoid: tuple = ()              # formats it cannot carry well


LOOKS: dict[str, Look] = {k.id: k for k in [
    Look("midnight", "dark", ("premium", "calm", "technical"), ("orbits", "network", "waves", "topo", "pixels", "flow")),
    Look("paper", "light", ("calm", "clear"), ("blobs", "iso", "bauhaus", "cards", "waves", "halftone")),
    Look("aqua", "light", ("friendly", "bright"), ("blobs", "waves", "cards", "orbits")),
    Look("blueprint", "dark", ("technical", "precise"), ("iso", "topo", "network", "waves", "grid")),
    Look("ink", "light", ("bold", "loud"), ("bauhaus", "chevrons", "pixels", "halftone"), places=("corner", "band")),
    Look("sketch", "light", ("playful", "human"), (), places=()),
    Look("editorial", "light", ("premium", "editorial"), ("topo", "waves"), places=("band", "corner")),
    Look("terminal", "dark", ("technical", "hacker"), ("pixels", "network", "chevrons", "grid")),
    Look("glass", "dark", ("premium", "modern"), ("blobs", "orbits", "rays", "flow")),
    Look("bold", "dark", ("bold", "energetic"), ("bauhaus", "rays", "chevrons", "waves", "arcs")),
    Look("duotone", "dark", ("bold", "modern"), ("orbits", "topo", "streaks", "arcs")),
    Look("neon", "dark", ("energetic", "kinetic"), ("streaks", "rays", "network", "grid"), places=("bg", "band")),
    Look("aurora", "light", ("calm", "premium", "friendly", "modern"), ("flow", "blobs", "orbits")),
    Look("swiss", "light", ("precise", "clear", "bold"), ("arcs", "halftone", "grid"), places=("corner", "band")),
    Look("grain", "dark", ("modern", "energetic", "kinetic"), ("flow", "halftone", "streaks")),
    Look("noir", "dark", ("premium", "editorial", "calm"), ("topo", "flow", "arcs"), places=("band", "corner")),
]}

# The site's colours only: brand blue, and its Mobile (teal) and AI (purple)
# category colours. templates/v2/design.css derives each from tokens.json.
ACCENTS = ("blue", "teal", "purple")
# The accent follows the subject where there is one — the site's own category
# colours — and rotates where there is not.
SERVICE_ACCENT = {"Web Development": "blue", "Mobile Apps": "teal", "AI Automation": "purple"}

ART_KINDS = ("orbits", "blobs", "iso", "waves", "topo", "bauhaus", "network", "cards", "chevrons", "streaks", "pixels", "rays",
             "flow", "halftone", "grid", "arcs")

# ── canvases & engines ────────────────────────────────────────────────────────

CANVAS = {
    "portrait": (1080, 1350),      # 4:5 — Instagram, LinkedIn documents, Threads
    "square": (1080, 1080),
    "story": (1080, 1920),         # 9:16 — stories, reel covers
    "landscape": (1600, 900),      # 16:9 — X
    "pin": (1000, 1500),           # 2:3 — Pinterest
}
PLATFORM_CANVAS = {"instagram": "portrait", "linkedin": "portrait", "threads": "portrait",
                   "x": "landscape", "pinterest": "pin", "facebook": "square"}

ENGINE_SCRIPTS = {
    "vega": ("vendor/vega.min.js", "vendor/vega-lite.min.js"),
    "mermaid": ("vendor/mermaid.min.js",),
    "prism": ("vendor/prism.js", "vendor/prism-python.min.js", "vendor/prism-typescript.min.js",
              "vendor/prism-bash.min.js", "vendor/prism-json.min.js", "vendor/prism-sql.min.js"),
    "rough": ("vendor/rough.js",),
}

# Icons the builders use themselves; content may name more (Lucide names).
BASE_ICONS = ("check", "x", "arrow-right", "bookmark", "send", "user-plus", "message-circle",
              "badge-check", "flag", "circle-check", "circle-x", "trending-up", "sparkles")


# Art that is solid shapes rather than hairlines. Behind dense text on a light
# ground it costs contrast (the first lab round measured 1.7:1 on a points list
# over Bauhaus tiles), so there it only sits in a corner or along a band.
SOLID_ART = frozenset({"bauhaus", "iso", "cards", "pixels", "blobs", "rays", "halftone"})
DENSE_FORMATS = frozenset({"checklist", "cheat_sheet", "flags", "vs", "steps", "framework", "tier_list", "timeline",
                           "quadrant", "code", "terminal", "chat", "recap", "notes", "iceberg", "decision_tree", "chart"})


def allowed_places(look_id: str, format_id: str, art: str) -> tuple:
    """Where this art may sit on this look for this format."""
    look = LOOKS[look_id]
    places = look.places or ("bg",)
    if look.tone == "light" and (format_id in DENSE_FORMATS or art in SOLID_ART):
        places = tuple(p for p in places if p != "bg") or ("corner",)
    return places


def engines_for(format_id: str, look: str) -> tuple:
    fmt = FORMATS[format_id]
    extra = ("rough",) if look == "sketch" else ()
    return tuple(dict.fromkeys(fmt.engines + extra))


# ── validation ────────────────────────────────────────────────────────────────


# Budgets are measured on the 4:5 portrait canvas. A canvas with less height
# holds less copy at the same type size - the first real square quote rendered
# at 0.61x - so text budgets shrink with it.
BUDGET_SCALE = {"portrait": 1.0, "pin": 1.0, "story": 1.0, "square": 0.82, "landscape": 0.8}


def budget(n: int, canvas: str = "portrait") -> int:
    """A text budget on this canvas. Only wrapping copy scales: a label of 48
    characters or fewer is one line, and every canvas is as wide as portrait
    or wider - it is height that a square canvas lacks."""
    if n <= 48:
        return n
    return int(n * BUDGET_SCALE.get(canvas, 1.0))


def count_cap(n: int, lo: int = 0, canvas: str = "portrait") -> int:
    """How many items a list may hold on this canvas. Six cheat-sheet cells in
    three rows render at 0.64x on a square canvas - a fifth less height - so
    long lists lose one or two items there, never going below their minimum."""
    if BUDGET_SCALE.get(canvas, 1.0) >= 1.0 or n < 5:
        return n
    return max(lo, n - (2 if n >= 6 else 1))


def validate(format_id: str, content: dict, layout: str = "", canvas: str = "portrait") -> list[str]:
    """Problems with a content spec, worded so they can be fed back to the writer.

    `layout` matters for the formats whose layouts read different fields:
    a vs table is built from rows, vs columns from each side's points.
    """
    fmt = FORMATS.get(format_id)
    if fmt is None:
        return [f"unknown format {format_id!r}"]
    if not isinstance(content, dict):
        return ["content must be an object"]
    problems: list[str] = []
    for name, spec in fmt.fields.items():
        _check(name, spec, content.get(name), problems, canvas)
    unknown = sorted(set(content) - set(fmt.fields))
    if unknown:
        problems.append(f"unknown field(s) {', '.join(unknown)} - remove them")
    if format_id == "decision_tree":
        problems += _check_tree(content.get("tree"))
    if format_id == "code" and isinstance(content.get("code"), str):
        lines = content["code"].split("\n")
        if len(lines) > 12:
            problems.append(f"code has {len(lines)} lines - max 12")
        wide = max((len(ln) for ln in lines), default=0)
        if wide > 46:
            problems.append(f"a code line is {wide} characters wide - max 46")
    if format_id == "quadrant":
        problems += _crowded_points(content.get("points"))
        if any(isinstance(p, dict) and isinstance(p.get(k), (int, float)) and not 0 <= p[k] <= 1
               for p in content.get("points") or [] for k in ("x", "y")):
            problems.append("quadrant positions run from 0 to 1 (0.5 is the middle) - rescale x and y")
    if format_id == "stat" and layout == "bento" and len(content.get("tiles") or []) < 2:
        problems.append("this stat is a BENTO: add 2-3 'tiles' of supporting figures from the facts")
    if format_id == "vs":
        sides = [content.get("left") or {}, content.get("right") or {}]
        if layout == "table":
            if not isinstance(content.get("rows"), list) or len(content.get("rows") or []) < 3:
                problems.append("this vs slide is a TABLE: write 3-5 'rows' (aspect, left, right), plus left.label and right.label")
        elif any(not isinstance(sd, dict) or len(sd.get("points") or []) < 2 for sd in sides):
            problems.append("this vs slide is COLUMNS: write 2-4 'points' for both left and right")
    return problems


def _check(name: str, spec: Field, value, problems: list[str], canvas: str = "portrait") -> None:
    if value is None or value == "" or value == []:
        if spec.required:
            problems.append(f"'{name}' is required")
        return
    if spec.kind == "text":
        if not isinstance(value, str):
            problems.append(f"'{name}' must be text")
        elif spec.max and len(_visible(value)) > budget(spec.max, canvas):
            problems.append(f"'{name}' is {len(_visible(value))} characters - max {budget(spec.max, canvas)}")
    elif spec.kind == "num":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            problems.append(f"'{name}' must be a number")
    elif spec.kind == "bool":
        if not isinstance(value, bool):
            problems.append(f"'{name}' must be true or false")
    elif spec.kind == "enum":
        if value not in spec.choices:
            problems.append(f"'{name}' must be one of {', '.join(spec.choices)}")
    elif spec.kind == "obj":
        if not isinstance(value, dict):
            problems.append(f"'{name}' must be an object")
            return
        for k, sub in (spec.fields or {}).items():
            _check(f"{name}.{k}", sub, value.get(k), problems, canvas)
    elif spec.kind == "list":
        if not isinstance(value, list):
            problems.append(f"'{name}' must be a list")
            return
        if len(value) < spec.min:
            problems.append(f"'{name}' has {len(value)} items - min {spec.min}")
        cap = count_cap(spec.max, spec.min, canvas) if spec.max else 0
        if cap and len(value) > cap:
            problems.append(f"'{name}' has {len(value)} items - max {cap}")
        for i, item in enumerate(value):
            if isinstance(spec.item, Field):
                _check(f"{name}[{i}]", spec.item, item, problems, canvas)
            elif isinstance(spec.item, dict):
                if not isinstance(item, dict):
                    problems.append(f"'{name}[{i}]' must be an object")
                    continue
                for k, sub in spec.item.items():
                    _check(f"{name}[{i}].{k}", sub, item.get(k), problems, canvas)


def _visible(s: str) -> str:
    """Text as the reader sees it: emphasis marks do not count against a budget."""
    return s.replace("==", "").replace("*", "")


def _crowded_points(points) -> list[str]:
    """Points whose labels would sit on top of each other. A label is far
    wider than it is tall, so points need more room side by side than above
    and below each other - the first real matrices put four labels in one
    corner and no placement could separate them."""
    pts = [p for p in (points or []) if isinstance(p, dict) and isinstance(p.get("x"), (int, float))
           and isinstance(p.get("y"), (int, float))]
    out: list[str] = []
    for i, a in enumerate(pts):
        for b in pts[i + 1:]:
            if abs(a["x"] - b["x"]) < 0.3 and abs(a["y"] - b["y"]) < 0.14:
                out.append(f"points '{a.get('label', '')}' and '{b.get('label', '')}' sit on top of each other - "
                           "spread them out (x 0.3 apart, or y 0.14 apart; positions run 0 to 1)")
    return out[:3]


def _check_tree(tree, depth: int = 0, counter: list | None = None) -> list[str]:
    counter = counter if counter is not None else [0]
    problems: list[str] = []
    counter[0] += 1
    if depth > 3:
        return ["decision tree is deeper than 3 levels"]
    if isinstance(tree, dict):
        q = tree.get("q")
        if not isinstance(q, str) or not q.strip():
            problems.append("every decision node needs a 'q' question")
        elif len(_visible(q)) > 48:
            problems.append(f"question '{q[:30]}...' is {len(q)} characters - max 48")
        for side in ("yes", "no"):
            if side not in tree:
                problems.append(f"decision node '{(q or '')[:30]}' is missing '{side}'")
            else:
                problems += _check_tree(tree[side], depth + 1, counter)
    elif isinstance(tree, str):
        if len(_visible(tree)) > 40:
            problems.append(f"leaf '{tree[:30]}...' is {len(tree)} characters - max 40")
    else:
        problems.append("decision tree nodes must be {q, yes, no} objects or leaf strings")
    if depth == 0 and counter[0] > 9:
        problems.append(f"decision tree has {counter[0]} boxes - max 9")
    return problems


@dataclass
class Choice:
    """One concrete design: everything the renderer needs except the words."""

    format: str
    layout: str
    look: str
    accent: str
    art: str = "none"
    place: str = "bg"
    seed: int = 1
    extras: dict = field(default_factory=dict)
