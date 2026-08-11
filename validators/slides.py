"""The pre-render gate: will these slides survive the template, and will they fit?

This runs before Chromium is ever started, and it exists because of what the
first review set actually shipped. From CONTENT_SYSTEM.md §1:

  * a literal `*` floating at 216px on the metric slide — the largest text in
    the deck, on the slide chosen precisely because the number should dominate
  * a metric value long enough to wrap, breaking the one thing that slide does

Both were invisible to the four content validators, because both are *rendering*
defects and those gates read prose. A caption can be perfect while the image
built from it is broken, and the image is the part people look at.

## Three checks, in order of how badly they fail

1. **Markup the template renders literally.** The template understands exactly
   one piece of syntax — `*emphasis*` — and escapes everything else. A backtick,
   a `[link](url)` or an `### heading` reaches the canvas as those characters,
   set in 99px type. There is no partial failure here: it is either clean or it
   is wrong in public.

2. **Structure.** Required fields present, `steps` actually a list of objects,
   `stats` exactly three, a chart with a numeric series. A missing field renders
   an empty box, which looks like a template with a slot nobody filled.

3. **Fit.** Field budgets from `campaign/visual.py`. The template auto-shrinks
   anything that would overflow, so this is not what stops a broken render — it
   is what stops a *shrunken* one. A cover headline at 60% of its intended size
   is technically fine and visibly wrong, and the fix is to write shorter, which
   only the writer can do.

Rejections come back as regeneration notes, so the usual outcome is a second
draft that fits rather than a missed slot.
"""
from __future__ import annotations

import re
from typing import Any

from campaign import visual

# ── Markup the template cannot render ────────────────────────────────────────
# Each entry is (pattern, what a reader would actually see).
_MARKUP = (
    (re.compile(r"`"), "a backtick"),
    (re.compile(r"!?\[[^\]]*\]\([^)]*\)"), "a markdown link"),
    (re.compile(r"^\s{0,3}#{1,6}\s", re.M), "a markdown heading marker"),
    (re.compile(r"(?<![A-Za-z0-9])__?[A-Za-z][^_\n]*__?(?![A-Za-z0-9])"), "markdown underscores"),
    (re.compile(r"^\s*[-+]\s+", re.M), "a markdown bullet"),
    (re.compile(r"^\s*>\s+", re.M), "a blockquote marker"),
    (re.compile(r"<[a-zA-Z/][^>]*>"), "an HTML tag"),
    (re.compile(r"\\n|\\t"), "an escaped newline written as two characters"),
    (re.compile(r"&(?:amp|lt|gt|quot|#\d+);"), "an HTML entity"),
)

# Text fields, by the key they arrive under. Anything not listed is structural
# (`steps`, `chart`) and is walked separately.
_TEXT_KEYS = (
    "kicker", "title", "body", "value", "label", "quote", "attribution",
    "pill", "note", "caption", "myth", "fact", "url",
)


def check(slides: list[dict], *, platform: str = "") -> list[str]:
    """Reasons these slides must not be rendered. Empty means they are fine."""
    reasons: list[str] = []
    if not slides:
        return reasons

    for index, slide in enumerate(slides, 1):
        where = f"slide {index}"
        if not isinstance(slide, dict):
            reasons.append(f"{where} is not an object")
            continue

        role = str(slide.get("role") or "").strip()
        archetype = visual.resolve(role)
        if archetype is None:
            reasons.append(
                f"{where}: unknown role {role!r} - use one of: {', '.join(visual.names())}"
            )
            continue

        reasons += _check_markup(slide, where)
        reasons += _check_theme_layout(slide, archetype, where)
        reasons += _check_required(slide, archetype, where)
        reasons += _check_structure(slide, archetype, where)
        reasons += _check_budgets(slide, archetype, where)

    return reasons


# ── 1. markup ────────────────────────────────────────────────────────────────
def _check_markup(slide: dict, where: str) -> list[str]:
    reasons: list[str] = []
    for key, text in _walk_text(slide):
        for pattern, described in _MARKUP:
            if pattern.search(text):
                reasons.append(
                    f"{where} {key}: contains {described}. Slides are plain text - "
                    "the only markup that renders is *asterisks* for emphasis."
                )
                break
        # An odd asterisk count means the writer opened an emphasis span and
        # never closed it. The template strips the stray one, so this never
        # renders broken — it renders with the emphasis silently missing, which
        # is worse to find later than a rejection now.
        if text.count("*") % 2:
            reasons.append(
                f"{where} {key}: an unpaired '*'. Emphasis is *opened and closed*, "
                "and a stray asterisk loses the emphasis entirely."
            )
    return reasons


# ── 2. structure ─────────────────────────────────────────────────────────────
def _check_theme_layout(slide: dict, archetype: visual.Archetype, where: str) -> list[str]:
    reasons: list[str] = []
    theme = slide.get("theme")
    if theme and theme not in archetype.themes:
        reasons.append(f"{where}: theme {theme!r} is not one of {', '.join(archetype.themes)}")
    layout = slide.get("layout")
    if layout and layout not in archetype.layouts:
        reasons.append(
            f"{where}: layout {layout!r} does not compose with {archetype.name} "
            f"- allowed: {', '.join(archetype.layouts)}"
        )
    return reasons


def _check_required(slide: dict, archetype: visual.Archetype, where: str) -> list[str]:
    missing = [f for f in archetype.required if not _has(slide, f)]
    if not missing:
        return []
    return [
        (
            f"{where} ({archetype.name}): missing required field(s) "
            f"{', '.join(missing)} - {archetype.brief}"
        )
    ]


def _has(slide: dict, field: str) -> bool:
    """Whether a required field is satisfied.

    `image` is satisfied by either `image` (a URL) or `svg` (inline markup),
    because those are two encodings of the same requirement — is there artwork
    on this slide — and the pipeline uses the second one. Checking only `image`
    rejected every `graphic_embed` in a review sweep whose artwork had been
    attached correctly, which is a validator failing the thing it was built to
    protect.
    """
    if field == "image":
        return _present(slide.get("image")) or _present(slide.get("svg"))
    return _present(slide.get(field))


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return True


_SHAPES: dict[str, tuple[str, int, int]] = {
    # role -> (field, min entries, max entries)
    "steps": ("steps", 3, 4),
    "checklist": ("items", 3, 5),
    "flow_diagram": ("nodes", 3, 5),
    "stat_row": ("stats", 3, 3),
}


def _check_structure(slide: dict, archetype: visual.Archetype, where: str) -> list[str]:
    reasons: list[str] = []
    name = archetype.name

    if name in _SHAPES:
        key, low, high = _SHAPES[name]
        entries = slide.get(key)
        if not isinstance(entries, list):
            reasons.append(f"{where}: {key!r} must be a list")
        elif not low <= len(entries) <= high:
            want = f"exactly {low}" if low == high else f"{low} to {high}"
            reasons.append(f"{where}: {key!r} needs {want} entries, got {len(entries)}")

    if name == "steps":
        for i, step in enumerate(slide.get("steps") or [], 1):
            if not isinstance(step, dict) or not str(step.get("title") or "").strip():
                reasons.append(f"{where}: step {i} needs a title")

    if name == "stat_row":
        for i, stat in enumerate(slide.get("stats") or [], 1):
            if not isinstance(stat, dict):
                reasons.append(f"{where}: stat {i} must be an object")
            elif not (_present(stat.get("value")) and _present(stat.get("label"))):
                reasons.append(f"{where}: stat {i} needs both a value and a label")

    if name in ("checklist", "flow_diagram"):
        key = "items" if name == "checklist" else "nodes"
        for i, entry in enumerate(slide.get(key) or [], 1):
            if not isinstance(entry, str) or not entry.strip():
                reasons.append(f"{where}: {key} entry {i} must be a non-empty string")

    if name == "before_after":
        for side in ("before", "after"):
            panel = slide.get(side)
            if not isinstance(panel, dict) or not str(panel.get("text") or "").strip():
                reasons.append(f"{where}: {side!r} must be an object with a 'text'")

    if archetype.charted:
        reasons += _check_chart(slide, name, where)

    return reasons


def _check_chart(slide: dict, name: str, where: str) -> list[str]:
    """Shape only. Whether the numbers are TRUE is the grounding gate's job."""
    chart = slide.get("chart")
    if not isinstance(chart, dict):
        return [f"{where}: {name} needs a 'chart' object"]

    if name == "donut":
        value = chart.get("value")
        if not isinstance(value, (int, float)) or not 0 <= float(value) <= 100:
            return [f"{where}: a donut's 'value' must be a number between 0 and 100"]
        if not str(chart.get("label") or "").strip():
            return [f"{where}: a donut needs a 'label' saying what the share is of"]
        return []

    series = chart.get("series")
    if not isinstance(series, list):
        return [f"{where}: chart 'series' must be a list"]
    low, high = (2, 2) if name == "comparison_bar" else (3, 5)
    if not low <= len(series) <= high:
        want = "exactly 2" if low == high else f"{low} to {high}"
        return [f"{where}: {name} needs {want} series entries, got {len(series)}"]

    reasons: list[str] = []
    for i, entry in enumerate(series, 1):
        if not isinstance(entry, dict):
            reasons.append(f"{where}: series entry {i} must be an object")
            continue
        if not str(entry.get("label") or "").strip():
            reasons.append(f"{where}: series entry {i} needs a label")
        if not isinstance(entry.get("value"), (int, float)):
            reasons.append(
                f"{where}: series entry {i} needs a numeric 'value' "
                "(a bare number, not '40%' or 'about 40')"
            )
        elif float(entry["value"]) < 0:
            reasons.append(f"{where}: series entry {i} has a negative value")
    if not reasons and all(float(e["value"]) == 0 for e in series):
        reasons.append(f"{where}: every bar is zero - there is nothing to draw")
    return reasons


# ── 3. fit ───────────────────────────────────────────────────────────────────
def _check_budgets(slide: dict, archetype: visual.Archetype, where: str) -> list[str]:
    budgets = archetype.budgets()
    reasons: list[str] = []
    for key, text in _walk_text(slide):
        budget = budgets.get(_budget_key(key))
        if budget and len(text) > budget:
            reasons.append(
                f"{where} {key}: {len(text)} characters, budget {budget}. "
                "Write it shorter - shrinking it to fit would leave the slide "
                "looking like a different design."
            )
    return reasons


def _budget_key(key: str) -> str:
    """Map a walked key like `steps[2].detail` back to its budget name."""
    if key.startswith("steps["):
        return "step_title" if key.endswith(".title") else "step_detail"
    if key.startswith("stats["):
        return "stat_value" if key.endswith(".value") else "stat_label"
    if key.startswith("items["):
        return "item"
    if key.startswith("nodes["):
        return "node"
    if key.startswith("chart.series["):
        return "series_label"
    if key.startswith(("before.", "after.")):
        return "note" if key.endswith(".label") else "body"
    return key


# ── walking ──────────────────────────────────────────────────────────────────
def _walk_text(slide: dict):
    """Every string a reader could end up seeing, as (path, text) pairs.

    Nested values are included deliberately. The asterisk bug was found on
    `metric.value`; the same class of defect on `steps[1].detail` or a chart's
    series label is no less public, just smaller.
    """
    for key in _TEXT_KEYS:
        value = slide.get(key)
        if isinstance(value, str) and value.strip():
            yield key, value

    for i, step in enumerate(slide.get("steps") or []):
        if isinstance(step, dict):
            for sub in ("title", "detail"):
                value = step.get(sub)
                if isinstance(value, str) and value.strip():
                    yield f"steps[{i + 1}].{sub}", value

    for i, stat in enumerate(slide.get("stats") or []):
        if isinstance(stat, dict):
            for sub in ("value", "label"):
                value = stat.get(sub)
                if isinstance(value, str) and value.strip():
                    yield f"stats[{i + 1}].{sub}", value

    for key in ("items", "nodes"):
        for i, entry in enumerate(slide.get(key) or []):
            if isinstance(entry, str) and entry.strip():
                yield f"{key}[{i + 1}]", entry

    for side in ("before", "after"):
        panel = slide.get(side)
        if isinstance(panel, dict):
            for sub in ("label", "text"):
                value = panel.get(sub)
                if isinstance(value, str) and value.strip():
                    yield f"{side}.{sub}", value

    chart = slide.get("chart")
    if isinstance(chart, dict):
        for sub in ("label", "unit", "source"):
            value = chart.get(sub)
            if isinstance(value, str) and value.strip():
                yield f"chart.{sub}", value
        for i, entry in enumerate(chart.get("series") or []):
            if isinstance(entry, dict) and isinstance(entry.get("label"), str):
                yield f"chart.series[{i + 1}].label", entry["label"]


def chart_numbers(slides: list[dict]) -> list[str]:
    """Every number a chart would draw, as text, for the grounding gate.

    CONTENT_SYSTEM.md §3.5: *a chart is just a number with a bigger font — an
    invented chart is an invented statistic.* The grounding gate reads prose, and
    a value living in `chart.series[0].value` is not prose, so without this the
    single largest number on a data slide would be the one number nobody checks.
    """
    out: list[str] = []
    for slide in slides or []:
        if not isinstance(slide, dict) or not visual.is_charted(slide.get("role", "")):
            continue
        chart = slide.get("chart")
        if not isinstance(chart, dict):
            continue
        unit = str(chart.get("unit") or "").strip()
        if isinstance(chart.get("value"), (int, float)):
            out.append(f"{_num(chart['value'])}%")
        for entry in chart.get("series") or []:
            if isinstance(entry, dict) and isinstance(entry.get("value"), (int, float)):
                out.append(f"{_num(entry['value'])}{unit}")
    return out


def _num(value: float | int) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)
