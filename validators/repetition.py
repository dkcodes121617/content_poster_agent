"""The repetition gate — CAMPAIGN.md §7.3.

Compares a draft against the last N published posts and rejects anything too
similar. This is what stops month three sounding like month one.

## Lexical similarity, not embeddings — and the tradeoff, stated

CAMPAIGN.md specifies embedding similarity. This uses word-trigram cosine
instead, for one reason: the alternative is `sentence-transformers`, which pulls
PyTorch into a container image that already carries Chromium. That is roughly
half a gigabyte and a much slower cold start, for an agent that compares a few
dozen short strings a week.

Be clear about what is given up. Embeddings catch *paraphrase* — "we build a
working prototype first" against "you see something real before paying".
Trigrams do not; they catch near-duplicates and heavy reuse of the same phrasing.

That is the failure mode that actually occurs here. The generator is given a
rotating pillar and a fresh facts snapshot each time, so the realistic risk is
recycled *wording*, not independently-arrived-at paraphrase. If published posts
ever start reading as genuine paraphrases of each other, this is the thing to
upgrade — and the check is behind one function so upgrading it is local.
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter

from wizcore.db.conn import connect, fetch_all

log = logging.getLogger("content_poster.repetition")


def _trigrams(text: str) -> Counter:
    words = re.findall(r"[a-z0-9']+", text.lower())
    if len(words) < 3:
        return Counter(words)
    return Counter(tuple(words[i : i + 3]) for i in range(len(words) - 2))


def similarity(a: str, b: str) -> float:
    """Cosine similarity over word trigrams, 0.0 to 1.0."""
    ca, cb = _trigrams(a), _trigrams(b)
    if not ca or not cb:
        return 0.0
    shared = set(ca) & set(cb)
    if not shared:
        return 0.0
    dot = sum(ca[t] * cb[t] for t in shared)
    na = math.sqrt(sum(v * v for v in ca.values()))
    nb = math.sqrt(sum(v * v for v in cb.values()))
    return dot / (na * nb) if na and nb else 0.0


def recent_posts(config, limit: int = 60) -> list[str]:
    """Captions of the last N published posts. [] if unavailable.

    Degrades rather than fails: an unreachable history means the gate cannot run,
    and blocking publication over that would let a database blip silence the
    whole campaign.
    """
    try:
        with connect(config.database_url, autocommit=True) as conn:
            rows = fetch_all(
                conn,
                # Queued hand-offs count: their copy is one tap from going live,
                # so a near-duplicate of one is a duplicate.
                "SELECT caption FROM content.social_posts "
                "WHERE status IN ('published', 'queued') AND caption IS NOT NULL "
                "ORDER BY published_at DESC LIMIT %s",
                (limit,),
            )
        return [r["caption"] for r in rows if r.get("caption")]
    except Exception:
        log.warning("could not read post history; repetition gate skipped", exc_info=True)
        return []


_OPENER_WORDS = 5


def opener(text: str, words: int = _OPENER_WORDS) -> str:
    """The first few words, normalised - the part a feed actually shows."""
    return " ".join(re.findall(r"[a-z0-9']+", (text or "").lower())[:words])


def check(text: str, history: list[str], threshold: float = 0.86) -> list[str]:
    # Whole-post similarity cannot see a recycled opener: 26 posts beginning
    # "AI tools for small business owners..." each had a different body and all
    # passed. The opener is what shows in the feed and on the profile grid, so a
    # repeated one reads as automation even when the rest is new.
    first = opener(text)
    if len(first.split()) == _OPENER_WORDS:
        for previous in history:
            if opener(previous) == first:
                return [(
                    f'opens with the same words as a recent post ("{first}...") - '
                    "open on a different hook"
                )]
    worst = 0.0
    for previous in history:
        worst = max(worst, similarity(text, previous))
        if worst >= threshold:
            return [
                f"too similar to a recent post (similarity {worst:.2f} >= {threshold})"
            ]
    return []
