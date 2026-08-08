"""The platform gate — CAMPAIGN.md §7.4 and §8.

Character limits, image counts, hashtag counts and link placement. Unglamorous,
and the gate most likely to actually fire: a caption two characters over
Instagram's limit is rejected by Meta with an error that names neither the limit
nor the field.

The LinkedIn link rule is the one that is strategy rather than API: LinkedIn
suppresses the reach of posts carrying an external link in the body, so the link
belongs in the first comment. Nothing rejects such a post — it just quietly
reaches far fewer people, which is exactly the kind of failure a validator
should catch because a human never would.
"""
from __future__ import annotations

import re

_URL = re.compile(r"https?://\S+", re.I)
_HASHTAG = re.compile(r"(?<!\w)#\w+")

# (caption limit, min images, max images, min hashtags, max hashtags)
LIMITS: dict[str, tuple[int, int, int, int, int]] = {
    "facebook":  (63000, 1, 1, 0, 2),
    # 8-12 hashtags per CAMPAIGN.md §8 — but in the FIRST COMMENT, never the
    # caption. Those are two different rules and conflating them was a real bug:
    # max_tags was 0, so every Instagram draft carrying hashtags was rejected,
    # three attempts running, on a platform that posts 3x a week. The caption
    # placement is enforced separately by the inline check below.
    "instagram": (2200, 1, 10, 8, 12),
    "threads":   (500, 0, 1, 0, 1),
    "linkedin":  (3000, 0, 10, 3, 3),   # exactly three; more measurably cuts reach
    "pinterest": (500, 1, 1, 0, 0),
    "devto":     (0, 0, 0, 0, 4),       # 0 = no caption limit; body is an article
    # Hand-written channels. The caption here is the WHOLE thread, split on
    # blank lines at hand-over; the per-tweet 280 ceiling is checked in
    # platforms/manual.py, which is the only place that knows where the splits
    # actually landed.
    "x":         (2400, 0, 4, 0, 2),
    "youtube":   (0, 0, 1, 0, 3),
}

# Hashtags that belong in the first comment rather than the caption, per platform.
FIRST_COMMENT_HASHTAGS = frozenset({"instagram"})


def check(platform: str, caption: str, hashtags: list[str], image_count: int) -> list[str]:
    reasons: list[str] = []
    limits = LIMITS.get(platform)
    if not limits:
        return [f"no platform limits defined for {platform!r}"]
    max_chars, min_img, max_img, min_tags, max_tags = limits

    # Hashtags are appended at publish time for platforms that take them in the
    # caption, so the length check has to include them or a post can pass here
    # and be rejected by the API.
    rendered = caption if platform in FIRST_COMMENT_HASHTAGS else _with_tags(caption, hashtags)
    if max_chars and len(rendered) > max_chars:
        reasons.append(f"caption is {len(rendered)} chars, over {platform}'s {max_chars}")
    if not caption.strip():
        reasons.append("caption is empty")

    if image_count < min_img:
        reasons.append(f"{platform} needs at least {min_img} image(s), got {image_count}")
    if image_count > max_img:
        reasons.append(f"{platform} allows at most {max_img} image(s), got {image_count}")

    inline = _HASHTAG.findall(caption)
    if platform in FIRST_COMMENT_HASHTAGS and inline:
        reasons.append(
            f"{len(inline)} hashtag(s) in the caption - on {platform} they belong in "
            "the first comment"
        )
    total_tags = len(hashtags)
    if total_tags < min_tags:
        reasons.append(f"{platform} wants {min_tags} hashtag(s), got {total_tags}")
    if total_tags > max_tags:
        reasons.append(f"{platform} allows at most {max_tags} hashtag(s), got {total_tags}")

    links = _URL.findall(caption)
    if platform == "linkedin" and links:
        reasons.append(
            "external link in a LinkedIn body - LinkedIn suppresses reach for those, "
            "so the link goes in the first comment"
        )
    if platform == "threads" and len(links) > 1:
        reasons.append(f"{len(links)} links in a Threads post; keep it to one")
    return reasons


def _with_tags(caption: str, hashtags: list[str]) -> str:
    if not hashtags:
        return caption
    return caption + "\n\n" + " ".join(_normalise(t) for t in hashtags)


def _normalise(tag: str) -> str:
    tag = tag.strip().lstrip("#")
    return f"#{tag}" if tag else ""
