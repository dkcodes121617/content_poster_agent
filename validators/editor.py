"""The editorial gate: is this draft worth publishing, not merely allowed?

## Why it exists

Every other validator catches a rule break: a banned phrase, an invented
figure, a duration, an over-long field. None of them can catch a dull post,
and dull is what the account was. Measured 24 Nov 2026 across 235 published
posts: 112 on Threads earned 2 followers, half of them reactions to news a
founder did not need, and the strongest openers were search-page copy ("If
you're hunting for an alternative to expensive software agencies..."). Every
one of them passed every gate.

So a second model reads each passing draft as the target reader would and
scores it. Below `EDITOR_MIN_SCORE` the draft goes back to the writer with the
editor's direction, the same way a validator rejection does. If the last
attempt still falls short, the slot is skipped: an empty slot costs nothing,
and a filler post teaches the audience to scroll past the next one.

## Failure direction

If the editor call itself fails (proxy down, unparseable reply), the draft is
let through. The validators that guard truth and policy have already passed;
the editor guards quality, and a proxy blip should not silence the account.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger("content_poster.editor")

_DIMENSIONS = ("hook", "value", "specificity", "originality", "overall")


@dataclass
class Review:
    ok: bool
    overall: int = 0
    scores: dict[str, int] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    revision: str = ""
    skipped: str = ""   # non-empty when the editor could not run

    def reasons(self) -> list[str]:
        """Rejection reasons in the shape the regeneration note expects."""
        out = [f"editor scored it {self.overall}/10 - not strong enough to publish"]
        out += [f"editor: {p}" for p in self.problems[:4]]
        if self.revision:
            out.append(f"editor's direction: {self.revision}")
        return out

    def summary(self) -> str:
        if self.skipped:
            return f"editor skipped ({self.skipped})"
        parts = " ".join(f"{k}={self.scores.get(k, '?')}" for k in _DIMENSIONS)
        return f"editor {'PASS' if self.ok else 'FAIL'} {parts}"


def parse(data, min_score: int) -> Review:
    """Turn the editor's JSON into a verdict. Raises ValueError if unusable."""
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")
    scores: dict[str, int] = {}
    for key in _DIMENSIONS:
        try:
            scores[key] = max(0, min(10, round(float(data.get(key)))))
        except (TypeError, ValueError):
            continue
    if "overall" not in scores:
        raise ValueError("editor reply has no overall score")
    problems = [str(p).strip() for p in (data.get("problems") or []) if str(p).strip()]
    return Review(
        ok=scores["overall"] >= min_score,
        overall=scores["overall"],
        scores=scores,
        problems=problems,
        revision=str(data.get("revision") or "").strip(),
    )


def salvage(raw: str) -> dict:
    """Recover scores from a reply whose JSON is malformed.

    The numbers are what decide the verdict, and they survive a broken string
    elsewhere in the object, so they are read field by field.
    """
    import re

    out: dict = {}
    for key in _DIMENSIONS:
        m = re.search(rf'"{key}"\s*:\s*(\d+(?:\.\d+)?)', raw or "")
        if m:
            out[key] = float(m.group(1))
    m = re.search(r'"revision"\s*:\s*"(.*?)"\s*[,}]', raw or "", re.S)
    if m:
        out["revision"] = m.group(1)
    m = re.search(r'"problems"\s*:\s*\[(.*?)\]', raw or "", re.S)
    if m:
        out["problems"] = [p.strip().strip('"') for p in re.split(r'",\s*"', m.group(1)) if p.strip()]
    return out


def review(client, config, *, platform: str, pillar: str, caption: str,
           slides_text: str = "", facts: str = "") -> Review:
    """Score one draft. Never raises; a failed call lets the draft through."""
    if not getattr(config, "editor_enabled", True):
        return Review(ok=True, skipped="disabled")
    from wizcore.llm.client import extract_json

    from prompts.library import EDITOR_SYSTEM, editor_user_prompt

    try:
        raw = client.complete(
            system=EDITOR_SYSTEM,
            user=editor_user_prompt(platform, pillar, caption, slides_text, facts),
            max_tokens=900,
            model=getattr(config, "editor_model", None),
        )
        data = extract_json(raw)
        if not isinstance(data, dict):
            # Seen on the first live run: an unescaped quote inside "problems"
            # made the object unparseable, and the extractor fell back to the
            # first parseable ARRAY - the problems list itself.
            data = salvage(raw)
        return parse(data, int(getattr(config, "editor_min_score", 7)))
    except Exception as e:  # quality gate fails open, see module doc
        log.warning("editor unavailable, letting the draft through: %s", str(e)[:160])
        return Review(ok=True, skipped=str(e)[:80])
