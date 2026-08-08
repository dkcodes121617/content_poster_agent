"""Turning the blog and case-study agents' output into distribution.

There is a second pipeline in this system that neither planning doc noticed:
**the blog agent publishes a post, and nothing tells anyone about it.** Same for
a case study. Those two agents produce the only genuinely grounded long-form
content WizCodes has, and it sat unshared.

No coupling is needed to fix that. This agent already reads the site repo for
grounding facts, so it can see `posts.ts` directly; it only needs to remember
what it has already promoted. `content.promoted_assets`, keyed
`(asset_type, slug)`, is that memory — which makes "pick the newest published
post not yet promoted" both genuinely grounded and impossible to duplicate.

## Why dev.to is not on the weekly calendar

Every other platform posts on a fixed rhythm because an audience learns a
schedule. Syndication is different: it is event-driven, firing when the blog
agent publishes rather than at 11:00 on a Monday. Putting it in the calendar
would mean either re-syndicating the same post weekly or skipping a publish that
landed on the wrong day.
"""
from __future__ import annotations

import logging

from wizcore.db.conn import connect, fetch_all

log = logging.getLogger("content_poster.promote")

ASSET_TYPES = ("blog", "case_study", "project")


def already_promoted(config, asset_type: str) -> set[str]:
    """Slugs of this type already promoted. Empty set if unreadable.

    An unreadable table degrades to "nothing promoted yet", which would
    re-promote — so callers treat an empty set as a reason to be conservative,
    and the UNIQUE insert below is the real guard.
    """
    try:
        with connect(config.database_url, autocommit=True) as conn:
            rows = fetch_all(
                conn,
                "SELECT slug FROM content.promoted_assets WHERE asset_type = %s",
                (asset_type,),
            )
        return {r["slug"] for r in rows}
    except Exception:
        log.warning("could not read promoted_assets", exc_info=True)
        return set()


def next_unpromoted(config, snapshot, asset_type: str = "blog") -> dict | None:
    """The newest published asset not yet promoted, or None.

    `existing_posts` is sorted newest-first by the snapshot, so the first miss
    is the right one. None is a perfectly normal answer — most runs have nothing
    new to syndicate.
    """
    done = already_promoted(config, asset_type)
    if asset_type == "blog":
        for post in snapshot.existing_posts:
            if post["slug"] not in done:
                return {
                    "asset_type": "blog",
                    "slug": post["slug"],
                    "title": post.get("title", ""),
                    "description": post.get("description", ""),
                    "url": f"{snapshot.url.rstrip('/')}/blog/{post['slug']}",
                    "tags": post.get("tags", []),
                }
        return None

    for project in snapshot.projects:
        if project.slug and project.slug not in done and not project.hide_status:
            return {
                "asset_type": asset_type,
                "slug": project.slug,
                "title": project.name,
                "description": project.description,
                "url": project.url,
                "tags": project.tech[:4],
            }
    return None


def mark_promoted(config, asset_type: str, slug: str, platforms: list[str]) -> bool:
    """Record a promotion. False if it was already recorded.

    The UNIQUE primary key `(asset_type, slug)` is what actually prevents a
    double-syndication, not the read above — a retry after a timeout finds the
    row and stops.
    """
    import json

    try:
        with connect(config.database_url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO content.promoted_assets (asset_type, slug, platforms) "
                "VALUES (%s, %s, %s::jsonb) ON CONFLICT (asset_type, slug) DO NOTHING",
                (asset_type, slug, json.dumps(platforms)),
            )
            return cur.rowcount > 0
    except Exception:
        log.error("could not record promoted asset %s/%s", asset_type, slug, exc_info=True)
        return False


def fetch_post_markdown(config, slug: str) -> str:
    """The published MDX body, for dev.to syndication. '' if unavailable.

    MDX is not Markdown: the site's posts use JSX components for charts and
    diagrams that dev.to cannot render. They are stripped rather than escaped,
    because a dev.to article showing `<BarChart data={...} />` as literal text
    looks broken in a way that reflects on the studio.
    """
    import re

    from wizcore.facts.site import SiteReader

    reader = SiteReader(
        repo=config.site_repo,
        token=config.site_read_token,
        ref=config.site_branch,
        local_dir=config.site_local_dir or None,
    )
    raw = reader.read(f"src/content/blog/{slug}.mdx")
    if not raw:
        return ""

    body = re.sub(r"^---\n.*?\n---\n", "", raw, count=1, flags=re.DOTALL)   # frontmatter
    body = re.sub(r"^import .*$", "", body, flags=re.M)                     # MDX imports
    # Self-closing and paired JSX components. Paired ones keep their inner text,
    # which is usually a caption worth keeping.
    body = re.sub(r"<([A-Z]\w*)[^>]*/>", "", body)
    body = re.sub(r"<([A-Z]\w*)[^>]*>(.*?)</\1>", r"\2", body, flags=re.DOTALL)
    return re.sub(r"\n{3,}", "\n\n", body).strip()
