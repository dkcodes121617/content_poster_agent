"""Search phrases and the opening-line gate.

On LinkedIn and dev.to the first words of a post become its URL. That makes the
opening line both the hook and the address, and a post whose first line missed
the phrase looks completely fine — which is exactly why it needs a gate rather
than a prompt line.
"""
from __future__ import annotations

import pytest

from campaign import keywords
from validators import seo

REQUIRED = ["linkedin", "devto"]


# ── the bank ─────────────────────────────────────────────────────────────────
def test_every_phrase_has_a_real_tier_and_pillars():
    from campaign.recipes import ALL_PILLARS

    for p in keywords.PHRASES:
        assert p.tier in keywords.TIERS, p.text
        assert p.pillars, p.text
        for pillar in p.pillars:
            assert pillar in ALL_PILLARS, (p.text, pillar)
        assert not p.region or p.region in ("US", "GB", "EU"), p.text


def test_the_high_intent_tiers_are_the_biggest():
    """Decision and cost phrases are where a buyer with a budget is."""
    counts = {t: sum(1 for p in keywords.PHRASES if p.tier == t) for t in keywords.TIERS}
    assert counts["decision"] >= counts["learn"]


def test_picking_is_weighted_toward_intent():
    """Not uniform: a decision phrase is four times as likely as a learn one."""
    from datetime import date, timedelta

    tiers = [
        keywords.pick("teach", platform="linkedin", today=date(2026, 8, 1) + timedelta(days=d)).tier
        for d in range(60)
    ]
    high = sum(1 for t in tiers if t in ("decision", "cost"))
    assert high > len(tiers) * 0.5, dict.fromkeys(tiers)


def test_the_same_slot_on_the_same_day_picks_the_same_phrase():
    from datetime import date

    args = dict(platform="linkedin", region="GB", today=date(2026, 8, 10))
    assert keywords.pick("teach", **args).text == keywords.pick("teach", **args).text


def test_regional_phrases_are_not_offered_to_other_regions():
    for phrase in keywords.eligible("teach", region="US"):
        assert phrase.region in ("", "US"), phrase.text


def test_every_pillar_has_at_least_one_phrase():
    from campaign.recipes import ALL_PILLARS

    for pillar in ALL_PILLARS:
        if pillar == "timely":
            continue     # timely posts carry a verified angle, not a keyword
        assert keywords.eligible(pillar), pillar


# ── matching the opening line ────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("opening", "phrase"),
    [
        ("Most founders start by comparing a freelancer vs an agency vs a studio.",
         "freelancer vs agency vs studio"),
        ("Wondering how much a SaaS MVP costs before you talk to anyone?",
         "how much does a SaaS MVP cost"),
        ("There is an alternative to expensive software agencies.",
         "alternative to expensive software agencies"),
        ("We offer a free prototype before you hire a developer.",
         "free prototype before hiring a developer"),
    ],
)
def test_a_natural_sentence_satisfies_the_phrase(opening, phrase):
    """The natural sentence is almost never the phrase verbatim.

    Requiring the literal string would force exactly the robotic phrasing that
    makes a post read as spam, so matching is on content words.
    """
    assert keywords.in_opening(opening, phrase), opening


@pytest.mark.parametrize(
    ("opening", "phrase"),
    [
        ("We build great software for businesses everywhere.",
         "freelancer vs agency vs studio"),
        ("A dental clinic in Leeds was losing nine appointments a week.",
         "how much does a SaaS MVP cost"),
    ],
)
def test_an_unrelated_opening_does_not_satisfy_the_phrase(opening, phrase):
    assert not keywords.in_opening(opening, phrase), opening


def test_the_phrase_must_be_near_the_start_not_buried():
    """Only the opening words become the slug, so only they count."""
    buried = (
        "We have been building software for three years now and over that time "
        "the question we hear most often is about a freelancer vs agency vs studio."
    )
    assert not keywords.in_opening(buried, "freelancer vs agency vs studio")


# ── the gate ─────────────────────────────────────────────────────────────────
def test_a_missed_phrase_is_rejected_on_slug_platforms():
    phrase = keywords.PHRASES[0]
    reasons = seo.check("We build great software.", phrase, "linkedin", REQUIRED)
    assert reasons and "URL" in reasons[0]


def test_a_missed_phrase_is_tolerated_elsewhere():
    """A preference must not cost a slot on a platform where it is not a URL."""
    phrase = keywords.PHRASES[0]
    assert seo.check("We build great software.", phrase, "threads", REQUIRED) == []


@pytest.mark.parametrize(
    "opening",
    [
        "We are the best software development company in Ahmedabad.",
        "The #1 development studio for startups.",
        "A world-class team of engineers.",
        "Leading software partner for UK business.",
    ],
)
def test_unprovable_superlatives_are_rejected_everywhere(opening):
    """Both unevidenced and the exact sentence somebody writes at a keyword."""
    assert [r for r in seo.check(opening, None, "threads", REQUIRED) if "superlative" in r]


def test_a_good_opening_passes_on_every_platform():
    phrase = keywords.PHRASES[0]
    opening = "Most founders start by comparing a freelancer vs an agency vs a studio."
    for platform in ("linkedin", "devto", "threads", "instagram"):
        assert seo.check(opening, phrase, platform, REQUIRED) == [], platform


def test_the_gate_reads_only_the_first_line():
    phrase = keywords.PHRASES[0]
    caption = (
        "We build great software.\n\n"
        "Most founders start by comparing a freelancer vs an agency vs a studio."
    )
    assert seo.check(caption, phrase, "linkedin", REQUIRED), "line two is not the slug"


def test_slug_preview_matches_what_linkedin_would_build():
    assert keywords.slug_preview("Most founders start by comparing a freelancer!") == \
        "most-founders-start-by-comparing-a-freelancer"


def test_no_phrase_means_no_seo_reason():
    """Turning `SEO_PHRASES` off must not reject anything."""
    assert seo.check("A perfectly ordinary opening line.", None, "linkedin", REQUIRED) == []
