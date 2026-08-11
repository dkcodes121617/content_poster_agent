"""The validator stack — what replaces the human approval gate.

Seven gates, in the order of how much damage passing them wrongly would do:

  1. grounding  - an invented statistic published in our name
  2. claims     - a delivery promise or a fixed price nobody agreed to
  3. voice      - a post that reads as machine-written
  4. repetition - month three sounding like month one
  5. platform   - a post the API rejects, or one LinkedIn quietly buries
  6. slides     - an image that renders broken, or renders markup literally
  7. seo        - an opening line nobody will ever search for, or one that
                  claims a superlative we cannot evidence

A draft failing any gate is not published. It is regenerated with the reasons
fed back, and if it still fails it is reported to Telegram and dropped.

A gate a human clicks through in two seconds was never really quality control.
A gate that refuses to publish a post containing an invented statistic is.

## The two gates added after the first review set

**claims** exists because the instruction it enforces — never a delivery
timeline, never a fixed price for us — is exactly the kind of thing a model
does helpfully and unprompted. Nothing about "you'll have a working prototype
in 48 hours" looks wrong; it reads well and commits the studio to something
nobody agreed to, in public.

**slides** exists because the other five gates all read prose, and a caption can
be perfect while the image built from it is broken. Every defect in
CONTENT_SYSTEM.md §1 passed every gate that existed at the time.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Grounding moved into wizcore: the Outreach agent needs exactly this check, and
# two copies drifting would mean one agent permitting what the other rejects.
from wizcore.facts import grounding

from validators import claims, platform, repetition, seo, voice
from validators import slides as slide_gate

# Pinterest is a SEARCH INDEX, not a feed. Several pins covering one subject
# from different angles, aimed at different phrases, is standard practice there
# and is how the platform is meant to be used — nobody's home page fills up with
# them, and each is found by a different query. The default threshold is tuned
# for a feed where a follower sees every post, and applying it to Pinterest
# rejects exactly the behaviour that makes Pinterest work.
#
# It is a relaxation, not a removal: 0.94 still catches a near-duplicate.
PLATFORM_REPETITION = {"pinterest": 0.94}


def repetition_threshold_for(platform: str, default: float) -> float:
    """The similarity ceiling for this platform.

    Never below the default — a per-platform value may loosen the gate where the
    platform's own conventions call for it, and may not tighten it silently.
    """
    return max(PLATFORM_REPETITION.get(platform, default), default)


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
    slides: list[dict] | None = None,
    repetition_threshold: float = 0.86,
    sources: list | None = None,
    phrase=None,
    seo_required: list[str] | None = None,
    pillar: str = "",
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

    `slides` is the raw slide list. Passing it turns on the pre-render gate and,
    more importantly, feeds chart values into grounding: a number living in
    `chart.series[0].value` is not prose, and without this the single largest
    figure on a data slide would be the one number nobody checks.
    """
    verdict = Verdict()
    threshold = repetition_threshold_for(platform_name, repetition_threshold)

    # CONTENT_SYSTEM.md §3.5 — a chart is just a number with a bigger font, so
    # an invented chart is an invented statistic. Appending the chart values as
    # text is what puts them in front of the same gate as everything else,
    # rather than building a second numeric check that could disagree with it.
    chart_text = " ".join(slide_gate.chart_numbers(slides or []))
    full_text = " ".join(x for x in (caption, slides_text, chart_text) if x).strip()

    for name, reasons in (
        ("grounding", grounding.check(full_text, snapshot, sources)),
        ("claims", claims.check(full_text)),
        ("voice", voice.check(caption)),
        ("repetition", repetition.check(caption, history, threshold)),
        ("platform", platform.check(platform_name, caption, hashtags, image_count)),
        ("slides", slide_gate.check(slides or [], platform=platform_name)),
        ("seo", seo.check(caption, phrase, platform_name, seo_required, pillar)),
    ):
        if reasons:
            verdict.ok = False
            verdict.failed_gates.append(name)
            verdict.reasons.extend(f"[{name}] {r}" for r in reasons)
    return verdict


__all__ = [
    "Verdict", "claims", "grounding", "platform", "repetition",
    "seo", "slide_gate", "validate", "voice",
]
