"""The production gates, run part by part on a v2 draft.

validators.validate() checks a post as one block of text. That is right for a
yes/no verdict and useless for a repair: "[claims] 'Week 1' ties a delivery to
a point in time" does not say which of eight slides to rewrite, so the whole
deck was regenerated and a different slide broke. Here each slide and the
caption are checked separately and every problem says where it is, which is
what lets design/prompt.write() ask for that slide alone.

The gates themselves are the same functions validators.validate() calls - no
second implementation that could disagree with the first.
"""
from __future__ import annotations

from wizcore.facts import grounding

from design.prompt import visible_text
from validators import claims, platform, repetition, repetition_threshold_for, seo, voice


def check(draft: dict, *, platform_name: str, snapshot, sources: list | None = None, history: list[str] | None = None,
          repetition_threshold: float = 0.86, phrase=None, seo_required: list[str] | None = None, pillar: str = "",
          image_count: int = 0) -> list[str]:
    problems: list[str] = []
    for i, slide in enumerate(draft.get("slides") or [], 1):
        text = visible_text([slide])
        problems += [f"slide {i}: [grounding] {r}" for r in grounding.check(text, snapshot, sources)]
        problems += [f"slide {i}: [claims] {r}" for r in claims.check(text)]
    caption = draft.get("caption", "")
    threshold = repetition_threshold_for(platform_name, repetition_threshold)
    for gate, reasons in (
        ("grounding", grounding.check(caption, snapshot, sources)),
        ("claims", claims.check(caption)),
        ("voice", voice.check(caption)),
        ("repetition", repetition.check(caption, history or [], threshold)),
        ("platform", platform.check(platform_name, caption, draft.get("hashtags") or [], image_count)),
        ("seo", seo.check(caption, phrase, platform_name, seo_required, pillar)),
    ):
        problems += [f"caption: [{gate}] {r}" for r in reasons]
    return problems
