"""The two gates that were rejecting good posts.

Both were caught by a real review sweep rather than by reasoning: three of
fourteen drafts failed, and two of those failures were the gate being wrong.
A gate that rejects good posts gets switched off, and then it stops catching
the bad ones too — so a false positive here costs more than it looks.
"""
from __future__ import annotations

import pytest
from wizcore.facts import grounding

from validators import voice

# ── grounding: what is actually a claim about us ─────────────────────────────
INVENTED = [
    "We built CuePilotPro for a dental group in Leeds.",
    "Our client Harrowgate Dental saw bookings double.",
    "We shipped MediSyncPlus last quarter.",
    "TaskForgeAI is one of our projects.",
]

NOT_A_CLAIM = [
    # A place. Rejected a real post: "a clinic in Denver".
    "We rebuilt the booking flow for a dental clinic in Denver.",
    # A sentence-initial verb. Rejected a real post.
    "Confirms arrive by text now. We built that in an afternoon.",
    # Ordinary capitalised nouns near first person.
    "We think Thursday afternoons are the worst time to ship anything.",
    "Our advice: read the contract before you sign it.",
    # A third party's product, plainly not claimed as ours.
    "Shopify put their commission up again. We have opinions.",
]


@pytest.mark.parametrize("text", INVENTED)
def test_an_invented_project_is_still_rejected(text, snapshot):
    assert grounding.check(text, snapshot), f"should reject: {text!r}"


@pytest.mark.parametrize("text", NOT_A_CLAIM)
def test_ordinary_capitalised_words_are_not_claims(text, snapshot):
    reasons = [r for r in grounding.check(text, snapshot) if "WizCodes project" in r]
    assert not reasons, f"false positive on {text!r}: {reasons}"


def test_real_projects_still_pass(snapshot):
    assert grounding.check("We built CuePilot for Bellwether.", snapshot) == []


def test_camelcase_keeps_the_wide_window(snapshot):
    """A product name near any first-person phrasing is enough."""
    assert grounding.check(
        "We spent three weeks on it and shipped RotaFlowPro to the client.", snapshot
    )


# ── voice: uniformity, measured relative to length ───────────────────────────
GOOD_SHORT = [
    # The exact copy CAMPAIGN.md §3 asks for, rejected by the old absolute rule.
    "The booking page worked. Nobody used it. Six seconds to load on a phone. No reminder.",
    (
        "Nine no-shows a week. That is the number the owner gave us. We looked at "
        "the booking page. It took six seconds to load."
    ),
]

UNIFORM = [
    # Twelve-word sentences, four in a row. The real signal.
    (
        "We help small businesses build software that works well for their teams. "
        "We focus on delivering value through careful planning and honest advice. "
        "We believe that good software should be simple and easy to maintain. "
        "We work closely with clients to understand what they actually need."
    ),
]


@pytest.mark.parametrize("text", GOOD_SHORT)
def test_short_punchy_copy_is_not_uniform(text):
    reasons = [r for r in voice.check(text) if "uniform" in r]
    assert not reasons, f"false positive on {text!r}: {reasons}"


@pytest.mark.parametrize("text", UNIFORM)
def test_genuinely_uniform_prose_is_still_caught(text):
    assert [r for r in voice.check(text) if "uniform" in r], text


def test_the_banned_phrases_still_fire():
    assert voice.check("Let's dive in and unlock a seamless, game-changing experience.")
