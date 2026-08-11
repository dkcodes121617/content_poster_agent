"""The claims gate.

Every REJECT case here is something a competent writer would produce unprompted
while trying to make the offer sound concrete. Every ALLOW case is something the
studio genuinely wants to say — and the allows matter more, because a gate that
blocks good posts gets switched off, and then the rejects stop working too.
"""
from __future__ import annotations

import pytest

from validators import claims

REJECT_TIMELINE = [
    "We'll have a working prototype in your hands in 48 hours.",
    "Your prototype is ready in two weeks.",
    "We build the first version in a week.",
    "Same-day turnaround on the prototype.",
    "Overnight delivery of a working build.",
    "24-hour turnaround, guaranteed.",
    "We can ship it by Friday.",
    "Prototype delivered within three days.",
    "It takes us about four weeks from brief to launch.",
    "Guaranteed delivery in 10 days.",
    "We'll build it in just one month.",
]

REJECT_PRICE = [
    "Our websites start at $5,000.",
    "A site like this costs about £8,000.",
    "We charge €3,000 for the build.",
    "Pricing starts from just $2,500.",
    "The package is priced at 4,000 USD.",
    "Our retainer is £1,200 a month.",
    "You'll pay around $10k for something like this.",
]

ALLOW = [
    # The offer itself — no number, no duration. If this ever fails, the gate is
    # banning the thing it exists to protect.
    "We build a working prototype before any money changes hands.",
    "See it before you pay for it. No retainer, no discovery fee.",
    # Industry pricing, properly attributed.
    "Most agencies bill discovery as a paid phase before anything gets built.",
    "Typical agency retainers run into five figures a month.",
    "Freelancers usually quote $2,000 for a landing page; agencies quote ten times that.",
    "The going rate for an agency discovery phase is around £5,000.",
    # Industry delivery times, attributed.
    "Most agencies take six months to get a first version in front of users.",
    "Typical studios need three weeks just to schedule a kickoff call.",
    # Performance figures — the best sentence a proof post can contain.
    "CuePilot answers in under 200ms on a mid-range phone.",
    "The booking page loaded in six seconds. That was the whole problem.",
    "We got median response under 200ms.",
    # History and scale, not delivery promises.
    "We have been building software for three years.",
    "Rotamatic handles shift planning for 40 staff across 3 clinics.",
    # Money that is not a price.
    "The commission rate falls to 15% for developers earning under $1,000,000 a year.",
    "They raised $2m last year and still could not get the app shipped.",
    # Process without duration.
    "You describe the problem, we build something real, then you decide.",
]


@pytest.mark.parametrize("text", REJECT_TIMELINE)
def test_rejects_delivery_timelines(text):
    assert claims.check(text), f"should have been rejected: {text!r}"


@pytest.mark.parametrize("text", REJECT_PRICE)
def test_rejects_fixed_prices_for_us(text):
    assert claims.check(text), f"should have been rejected: {text!r}"


@pytest.mark.parametrize("text", ALLOW)
def test_allows_legitimate_claims(text):
    assert claims.check(text) == [], f"should have passed: {text!r}\n{claims.check(text)}"


def test_attribution_is_sentence_scoped():
    """A window would leak the attribution from one sentence into the next."""
    text = (
        "Most agencies charge £8,000 for a marketing site. "
        "We charge £6,000 for the same thing."
    )
    reasons = claims.check(text)
    assert len(reasons) == 1, reasons
    assert "6,000" in reasons[0]


def test_reasons_are_deduplicated():
    text = "Ready in 48 hours. Ready in 48 hours. Ready in 48 hours."
    assert len(claims.check(text)) == 1


def test_empty_input_passes():
    assert claims.check("") == []
    assert claims.check("   ") == []
