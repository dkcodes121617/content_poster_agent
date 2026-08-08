"""dev.to syndication — the cheapest reach in the campaign.

One API call republishes a post the blog agent already wrote, to a developer
audience, with a canonical URL pointing back at wizcodes.site. It can out-traffic
the original and costs nothing.

Event-driven rather than scheduled: it fires when there is a post that has not
been syndicated, which is why it is not on the weekly calendar. `promoted_assets`
is the memory that makes "has not been syndicated" answerable without asking
dev.to.

The canonical URL is the whole point. Without it this competes with the original
for the same search terms instead of feeding it — which would make syndication
actively harmful to the SEO the blog agent exists to build.
"""
from __future__ import annotations

import logging

from wizcore.db.actions import claim, make_key
from wizcore.facts.site import SiteReader
from wizcore.facts.snapshot import build_snapshot
from wizcore.obs.log import log_event
from wizcore.telegram.send import esc, send

from campaign import promote
from config import AGENT_NAME
from platforms import Draft, get_platform

log = logging.getLogger("content_poster.syndicate")


def run(config, run_id: str = "") -> dict:
    """Syndicate the newest un-syndicated blog post. Returns counters."""
    counters = {"syndicated": 0, "syndicate_skipped": 0, "syndicate_failed": 0}
    if "devto" not in config.active_platforms():
        counters["syndicate_skipped"] = 1
        log.info("devto not in PLATFORMS_ENABLED; nothing to do")
        return counters

    reader = SiteReader(
        repo=config.site_repo,
        token=config.site_read_token,
        ref=config.site_branch,
        local_dir=config.site_local_dir or None,
    )
    snapshot = build_snapshot(reader)
    asset = promote.next_unpromoted(config, snapshot, "blog")
    if not asset:
        log.info("no unsyndicated blog posts")
        return counters

    body = promote.fetch_post_markdown(config, asset["slug"])
    if not body:
        # A post in the registry with no MDX file is a site-repo problem, not a
        # syndication problem. Marking it promoted would hide that permanently.
        log.warning("no MDX body for %s; leaving unpromoted", asset["slug"])
        counters["syndicate_failed"] = 1
        return counters

    draft = Draft(
        platform="devto",
        pillar="blog_teaser",
        caption=asset["description"] or asset["title"],
        title=asset["title"],
        link=asset["url"],
        body_markdown=body,
        hashtags=[t for t in asset.get("tags", [])][:4],
    )

    # Keyed on the slug, not the date: syndicating one post twice is the failure
    # to prevent, and it could otherwise happen on any day the ledger was
    # unreachable.
    key = make_key(AGENT_NAME, "syndicate_devto", asset["slug"])
    with claim(
        key, agent=AGENT_NAME, kind="syndicate_devto", target=asset["slug"],
        dry_run=config.dry_run, url=config.database_url,
    ) as c:
        if not c.granted:
            log.info("syndication skipped for %s: %s", asset["slug"], c.reason)
            counters["syndicate_skipped"] = 1
            return counters

        if config.dry_run:
            c.succeeded(dry_run=True)
            send(
                f"📰 <b>DRY RUN</b> - would syndicate to dev.to\n"
                f"{esc(asset['title'])}\ncanonical: {esc(asset['url'])}\n"
                f"{len(body)} chars of markdown",
                topic="content", dry_run=True,
            )
            counters["syndicated"] = 1
            return counters

        result = get_platform("devto", config).publish(draft)
        if result.ok:
            c.succeeded(external_id=result.external_id, permalink=result.permalink)
            promote.mark_promoted(config, "blog", asset["slug"], ["devto"])
            counters["syndicated"] = 1
            send(
                f"📰 <b>Syndicated to dev.to</b>\n{esc(asset['title'])}\n"
                f'<a href="{esc(result.permalink)}">{esc(result.permalink)}</a>',
                topic="content", dry_run=False,
            )
        else:
            c.failed(error=result.error)
            counters["syndicate_failed"] = 1
            log.error("dev.to syndication failed: %s", result.error)

    log_event(log, "syndicate.done", **counters)
    return counters
