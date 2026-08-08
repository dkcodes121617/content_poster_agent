"""The validator stack — what replaces the human approval gate.

Four gates, in the order of how much damage passing them wrongly would do:

  1. grounding  - an invented statistic published in our name
  2. voice      - a post that reads as machine-written
  3. repetition - month three sounding like month one
  4. platform   - a post the API rejects, or one LinkedIn quietly buries

A draft failing any gate is not published. It is regenerated with the reasons
fed back, and if it still fails it is reported to Telegram and dropped.

A gate a human clicks through in two seconds was never really quality control.
A gate that refuses to publish a post containing an invented statistic is.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Grounding moved into wizcore: the Outreach agent needs exactly this check, and
# two copies drifting would mean one agent permitting what the other rejects.
from wizcore.facts import grounding

from validators import platform, repetition, voice


@dataclass
class Verdict:
    ok: bool = True
    reasons: list[str] = field(default_factory=list)
    failed_gates: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return "; ".join(self.reasons[:6]) if self.reasons else "passed all gates"


def validate(
    *,
    caption: str,
    hashtags: list[str],
    image_count: int,
    platform_name: str,
    snapshot,
    history: list[str],
    slides_text: str = "",
    repetition_threshold: float = 0.86,
    sources: list | None = None,
) -> Verdict:
    """Run every gate. Slides are checked for grounding too, never only the caption.

    That matters: a carousel's numbers live on the slides, and checking only the
    caption would leave the largest text on the image — the part people actually
    read — completely unverified.

    `sources` is captured evidence for a timely post (`content.trend_sources`).
    Passing it lets an external figure through **only** if it appears in
    something we actually fetched and stored; passing nothing means every
    external figure is rejected, which is the correct default for evergreen
    content. Claims about WizCodes are unaffected either way — those can only
    ever come from the site repo.
    """
    verdict = Verdict()
    full_text = f"{caption}\n{slides_text}".strip()

    for name, reasons in (
        ("grounding", grounding.check(full_text, snapshot, sources)),
        ("voice", voice.check(caption)),
        ("repetition", repetition.check(caption, history, repetition_threshold)),
        ("platform", platform.check(platform_name, caption, hashtags, image_count)),
    ):
        if reasons:
            verdict.ok = False
            verdict.failed_gates.append(name)
            verdict.reasons.extend(f"[{name}] {r}" for r in reasons)
    return verdict


__all__ = ["Verdict", "grounding", "platform", "repetition", "validate", "voice"]
