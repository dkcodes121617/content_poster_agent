"""Chunked Telegram messages must each be valid HTML on their own.

Telegram parses every chunk as a standalone message, so a <pre> block that
starts in one chunk and ends in the next produces two 400s and BOTH messages
are dropped. That happened in production: the Outreach hand-over on 18 Aug
created nine drafts and delivered none, because each draft is wrapped in <pre>
and the message ran past the chunk size.

    HTTP 400: can't parse entities: Can't find end tag corresponding to
              start tag "pre"
    HTTP 400: can't parse entities: Unexpected end tag at byte offset 323
"""
from __future__ import annotations

import re

import pytest

from wizcore.telegram.send import _MAX, _chunks, _open_tags

TAGS = ("pre", "code", "b", "i", "u", "s", "blockquote")


def _balanced(fragment: str) -> bool:
    """True when every spanning tag opened in `fragment` is also closed."""
    return _open_tags(fragment) == []


def _strip_tags(text: str) -> str:
    return re.sub(r"</?[a-zA-Z]+[^>]*>", "", text)


def test_short_message_is_untouched():
    msg = "<b>hello</b>"
    assert _chunks(msg) == [msg]


def test_pre_block_split_across_chunks_stays_valid():
    """The exact production failure."""
    draft = "\n".join(f"line {i} of a long outreach draft" for i in range(400))
    msg = f"<b>Send this by hand</b>\n<pre>{draft}</pre>\nMark done with /done 12"
    chunks = _chunks(msg)

    assert len(chunks) > 1, "message needs to actually split for this to test anything"
    for i, chunk in enumerate(chunks):
        assert _balanced(chunk), f"chunk {i} has unbalanced tags: {chunk[:120]!r}"
        assert len(chunk) <= _MAX, f"chunk {i} is {len(chunk)} bytes, over Telegram's limit"


def test_no_visible_text_is_lost():
    """Balancing must add tags, never drop content."""
    draft = "\n".join(f"paragraph {i} " + "x" * 60 for i in range(200))
    msg = f"<pre>{draft}</pre>"
    joined = "".join(_strip_tags(c) for c in _chunks(msg))
    assert _strip_tags(msg).replace("\n", "") == joined.replace("\n", "")


@pytest.mark.parametrize("tag", TAGS)
def test_every_spanning_tag_is_reopened(tag):
    body = "\n".join("y" * 80 for _ in range(120))
    chunks = _chunks(f"<{tag}>{body}</{tag}>")
    assert len(chunks) > 1
    for chunk in chunks:
        assert _balanced(chunk)


def test_nested_tags_survive_a_split():
    body = "\n".join("z" * 70 for _ in range(140))
    chunks = _chunks(f"<b>heading</b>\n<pre><code>{body}</code></pre>")
    assert len(chunks) > 1
    for chunk in chunks:
        assert _balanced(chunk)


def test_a_single_enormous_line_still_chunks():
    """No safe boundary inside it, but the output must still be valid."""
    chunks = _chunks("<pre>" + "q" * 12000 + "</pre>")
    assert len(chunks) > 1
    for chunk in chunks:
        assert _balanced(chunk)
        assert len(chunk) <= _MAX


def test_malformed_input_does_not_raise():
    """Model-generated text is not guaranteed well-formed markup."""
    for junk in ("</pre>" + "a" * 5000, "<pre>" * 40 + "b" * 5000, "<b><i>" + "c" * 5000 + "</b>"):
        for chunk in _chunks(junk):
            assert len(chunk) <= _MAX
