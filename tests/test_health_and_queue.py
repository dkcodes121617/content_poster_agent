"""The fixes from the 4 Oct audit: honest post status, varied openers, and a
health check that reads a stored traceback the way a person needs it read."""
from __future__ import annotations

from campaign import health, keywords
from platforms.base import PublishResult
from validators import repetition


# ── health: the exception line, not the traceback's first or last line ──────
def test_error_summary_finds_the_exception_line():
    traceback = (
        "Traceback (most recent call last):\n"
        '  File "/root/graph/nodes.py", line 428, in screen\n'
        "    blocked, reason = suppression.is_suppressed(\n"
        "psycopg.errors.FeatureNotSupported: input of anonymous composite types is "
        "not implemented\n"
        "CONTEXT:  unnamed portal parameter $1 = '...'\n"
        "During task with name 'screen' and id '52139b80'\n"
    )
    summary = health.error_summary(traceback)
    assert summary.startswith("psycopg.errors.FeatureNotSupported")


def test_error_summary_falls_back_to_the_last_line():
    assert health.error_summary("no terminal status; container was killed mid-run") == (
        "no terminal status; container was killed mid-run"
    )
    assert health.error_summary("") == "no error recorded"


def test_blog_line_speaks_only_when_stale():
    from datetime import date

    assert health._blog_line(date(2026, 9, 28), date(2026, 10, 4))
    assert health._blog_line(date(2026, 10, 3), date(2026, 10, 4)) == []


# ── repetition: a recycled opener is rejected even with a new body ──────────
def test_repeated_opener_is_rejected():
    history = ["AI tools for small business owners just got simpler. Meta handed..."]
    draft = "AI tools for small business owners are everywhere now, but the real cost..."
    reasons = repetition.check(draft, history)
    assert reasons and "same words" in reasons[0]


def test_different_opener_passes():
    history = ["AI tools for small business owners just got simpler. Meta handed..."]
    draft = "Copying thirty tracking numbers by hand is an hour a day you never get back."
    assert repetition.check(draft, history) == []


# ── keywords: the search phrase is the opener only where it becomes the URL ──
def test_phrase_is_the_opener_only_on_slug_platforms():
    phrase = keywords.PHRASES[0]
    on_linkedin = keywords.brief(phrase, "linkedin")
    on_threads = keywords.brief(phrase, "threads")
    assert "FIRST sentence" in on_linkedin
    assert "never as the first words" in on_threads
    assert "FIRST sentence" not in on_threads


# ── status: a hand-off is queued, not published ─────────────────────────────
def test_manual_hand_off_is_recorded_as_queued():
    from graph.nodes import _post_status

    queued = PublishResult(platform="linkedin", ok=True, external_id="manual:42")
    live = PublishResult(platform="threads", ok=True, external_id="1789",
                         permalink="https://www.threads.com/@wiz_codes/post/x")
    failed = PublishResult.failure("instagram", "HTTP 400")
    assert _post_status(queued) == "queued"
    assert _post_status(live) == "published"
    assert _post_status(failed) == "failed"
