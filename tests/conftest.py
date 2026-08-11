"""Shared fixtures.

Everything here is offline. A test suite that needs the network, the database
or an LLM is a test suite that gets skipped when it matters most — and the
defects this suite exists to catch (literal asterisks on the largest text in a
deck, a "prototype in 48 hours" claim, a chart with an invented number) are all
pure functions of the input. None of them need a live anything.

The one exception is `rendered`, which drives real Chromium. It is opt-in via
`--render` and skipped otherwise, because it costs ~1s per slide.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_ROOT = Path(__file__).resolve().parent.parent
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from wizcore.facts.snapshot import FactsSnapshot, ProjectFact, TestimonialFact  # noqa: E402


def pytest_addoption(parser):
    parser.addoption(
        "--render",
        action="store_true",
        default=False,
        help="run the Chromium render tests (slow: launches a real browser)",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "render: needs headless Chromium")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--render"):
        return
    skip = pytest.mark.skip(reason="needs --render (launches Chromium)")
    for item in items:
        if "render" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def snapshot() -> FactsSnapshot:
    """A small, fully-known facts snapshot.

    Deliberately not the real one. These tests assert what the grounding gate
    accepts and rejects, and that has to be decidable by reading the test —
    against the live site repo the same assertions would flip silently the next
    time someone adds a project.
    """
    return FactsSnapshot(
        brand_name="WizCodes",
        tagline="Software that earns its keep",
        url="https://wizcodes.site",
        locality="Ahmedabad",
        region="Gujarat",
        country="India",
        founding_year="2023",
        services=[
            {"name": "Web Development", "slug": "web-development",
             "oneLineDescription": "Sites and platforms that load fast."},
            {"name": "Mobile Apps", "slug": "mobile-apps",
             "oneLineDescription": "iOS and Android from one codebase."},
            {"name": "AI Automation", "slug": "ai-automation",
             "oneLineDescription": "Agents that do the repetitive work."},
        ],
        projects=[
            ProjectFact(
                id="cuepilot", name="CuePilot", category="Web Development",
                industry="Hospitality", client="Bellwether", client_country="United Kingdom",
                description="A booking desk that answers in under 200ms.",
                tech=["Next.js", "Postgres"], slug="cuepilot",
            ),
            ProjectFact(
                id="rotamatic", name="Rotamatic", category="Mobile Apps",
                industry="Healthcare", client="Northgate Dental", client_country="United States",
                description="Shift planning for 40 staff across 3 clinics.",
                tech=["Flutter"], slug="rotamatic",
            ),
        ],
        open_source=[
            {"name": "Bulkhead", "description": "Rate limiting for FastAPI.",
             "downloads": "12,400", "slug": "bulkhead", "status": "live"},
        ],
        testimonials=[
            TestimonialFact(
                name="Priya Raman", country="United States", platform="Upwork",
                text="They shipped the thing they said they would.",
                role="Founder", company="Northgate Dental",
            ),
        ],
        existing_posts=[
            {"slug": "what-software-costs", "title": "What software actually costs",
             "description": "A buyer's guide.", "tags": ["pricing"], "date": "2026-07-01"},
        ],
        playbook_excerpt="",
    )


@pytest.fixture(scope="session")
def sources() -> list[dict]:
    """Captured trend evidence, shaped like `content.trend_sources` rows."""
    return [
        {
            "publisher": "The Register",
            "title": "App store commission drops to 15% for small developers",
            "extract": (
                "The commission rate falls to 15% for developers earning under "
                "$1,000,000 a year. Around 78% of listed apps qualify."
            ),
        },
    ]
