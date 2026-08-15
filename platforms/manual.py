"""X and YouTube — written by the agent, posted by a human.

Neither has a usable free API. That is not a gap to fill later: X's write access
is metered and expensive, and automating YouTube uploads for a studio with no
video pipeline would be building the wrong thing. So the agent does the writing,
which is the part that takes judgement, and hands over something formatted for
copy-paste.

`content.manual_queue` is what makes this a queue rather than a message. An item
handed over and never posted appears in the daily digest instead of scrolling
away in Telegram — which is the difference between "X is a manual channel" and
"X quietly stopped happening in March".
"""
from __future__ import annotations

import json
import logging

from wizcore.db.conn import connect
from wizcore.telegram.send import esc, send, send_album, send_photo

from platforms.base import Draft, Platform, PublishResult

log = logging.getLogger("content_poster.platforms.manual")

# X counts characters per tweet, not per thread. 280 is the free-tier limit and
# the agent writes to it rather than assuming a paid account.
X_TWEET_LIMIT = 280


class ManualPlatform(Platform):
    """Not a publisher. It records the hand-over and reports it."""

    name = "manual"
    needs_hosted_images = False

    def publish(self, draft: Draft) -> PublishResult:
        tweets = _split_thread(draft.caption) if draft.platform == "x" else [draft.caption]
        over = [i for i, t in enumerate(tweets, 1) if len(t) > X_TWEET_LIMIT]

        blocks = [
            (
                f"✍️ <b>Post this on {esc(draft.platform)} yourself</b> "
                f"({esc(draft.pillar)})"
            ),
            "",
        ]
        for index, tweet in enumerate(tweets, 1):
            label = f"{index}/{len(tweets)}" if len(tweets) > 1 else ""
            blocks.append(f"<b>{label}</b>" if label else "")
            blocks.append(f"<pre>{esc(tweet)}</pre>")
        if draft.hashtags:
            blocks.append("hashtags: " + esc(" ".join(f"#{h.lstrip('#')}" for h in draft.hashtags)))
        if over:
            blocks.append(
                f"⚠️ tweet(s) {', '.join(map(str, over))} exceed {X_TWEET_LIMIT} characters"
            )
        send("\n".join(b for b in blocks if b), topic="content", dry_run=self.config.dry_run)

        # The images as ACTUAL photos, not links. A hand-posted draft is copied
        # on a phone, and a URL means opening a browser, downloading, then
        # switching apps; a photo in the chat is a long-press and save. The
        # whole point of this queue is that posting it by hand is quick.
        hosted = [u for u in draft.image_urls if u.startswith("http")][:10]
        if hosted:
            caption = f"images for the {esc(draft.platform)} post above"
            if len(hosted) > 1:
                send_album(hosted, caption, topic="content", dry_run=self.config.dry_run)
            else:
                send_photo(hosted[0], caption, topic="content", dry_run=self.config.dry_run)

        queue_id = self._record(draft, tweets)
        if queue_id:
            send(
                f"Mark done with <code>/done {queue_id}</code> once posted.",
                topic="content", dry_run=self.config.dry_run, silent=True,
            )
        return PublishResult(
            platform=draft.platform,
            ok=True,
            # Not a real post id. Naming it plainly keeps a hand-over from being
            # mistaken for a publish anywhere downstream.
            external_id=f"manual:{queue_id or 'unrecorded'}",
        )

    def _record(self, draft: Draft, tweets: list[str]) -> int | None:
        if self.config.dry_run:
            return None
        try:
            with connect(self.config.database_url, autocommit=True) as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO content.manual_queue "
                    "(platform, pillar, body, hashtags, image_urls, idempotency_key) "
                    "VALUES (%s,%s,%s,%s::jsonb,%s::jsonb,%s) "
                    "ON CONFLICT (idempotency_key) DO NOTHING RETURNING id",
                    (
                        draft.platform,
                        draft.pillar,
                        "\n\n".join(tweets),
                        json.dumps(draft.hashtags),
                        json.dumps(draft.image_urls),
                        draft.raw.get("idempotency_key"),
                    ),
                )
                row = cur.fetchone()
                return row["id"] if row else None
        except Exception:
            log.warning("could not record manual_queue row", exc_info=True)
            return None


def _split_thread(text: str) -> list[str]:
    """Split authored copy into tweets.

    Blank lines are the author's own break points, so they are honoured first.
    Only a part that is still over the limit gets split on sentences — guessing
    where a thread should break reads worse than a slightly long tweet the
    author can trim.
    """
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    out: list[str] = []
    for part in parts:
        if len(part) <= X_TWEET_LIMIT:
            out.append(part)
            continue
        current = ""
        import re

        for sentence in re.split(r"(?<=[.!?])\s+", part):
            if len(current) + len(sentence) + 1 > X_TWEET_LIMIT and current:
                out.append(current.strip())
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            out.append(current.strip())
    return out or [text]


def pending(conn, limit: int = 50) -> list[dict]:
    from wizcore.db.conn import fetch_all

    return fetch_all(
        conn,
        "SELECT id, platform, pillar, created_at FROM content.manual_queue "
        "WHERE status = 'pending' ORDER BY created_at LIMIT %s",
        (limit,),
    )


def mark_done(conn, queue_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE content.manual_queue SET status = 'done', done_at = now() "
            "WHERE id = %s AND status = 'pending'",
            (queue_id,),
        )
        return cur.rowcount > 0
