"""Retry behaviour of the proxy client.

These run against a real local HTTP server rather than a mocked session,
because every bug this file exists to prevent lived in the gap between "what
the code does with a Response object" and "what the server actually sends".
The 529 case in particular was a status-code branch, invisible to any test
that stubbed the transport.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from wizcore.llm.client import LLMClient, LLMError, LLMTransient

_OK_BODY = json.dumps(
    {
        "content": [{"type": "text", "text": "ok"}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "stop_reason": "end_turn",
    }
).encode()


class _Server:
    """Replays a scripted list of (status, headers); the last entry repeats."""

    def __init__(self, script):
        self.script = script
        self.hits: list[tuple[float, int]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # keep pytest output clean
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("content-length", 0)))
                status, extra = outer.script[min(len(outer.hits), len(outer.script) - 1)]
                outer.hits.append((time.monotonic(), status))
                body = _OK_BODY if status == 200 else b'{"error":"x"}'
                self.send_response(status)
                for key, value in (extra or {}).items():
                    self.send_header(key, value)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._httpd = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._httpd.server_address[1]}"

    def close(self):
        self._httpd.shutdown()


def _call(script):
    server = _Server(script)
    try:
        client = LLMClient(base_url=server.url, api_key="test")
        error = None
        try:
            client.complete(system="s", user="u", max_tokens=16)
        except Exception as exc:  # noqa: BLE001
            error = exc
        return server, error
    finally:
        server.close()


def test_529_overloaded_is_retried():
    """The bug this file was written for.

    529 is Anthropic's "temporarily overloaded" and is explicitly retryable, but
    it fell through to the permanent branch and aborted the whole run the first
    time capacity was tight.
    """
    server, error = _call([(529, None), (529, None), (200, None)])
    assert error is None
    assert len(server.hits) == 3


@pytest.mark.parametrize("status", [408, 409, 425, 429, 500, 502, 503, 504, 529])
def test_transient_statuses_retry(status):
    server, error = _call([(status, None), (200, None)])
    assert error is None, f"{status} should have been retried"
    assert len(server.hits) == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404, 413])
def test_permanent_statuses_do_not_retry(status):
    """Retrying these burns time and money to get the identical answer."""
    server, error = _call([(status, None)])
    assert isinstance(error, LLMError)
    assert len(server.hits) == 1


def test_retry_after_header_is_obeyed():
    """When the server says how long to wait, guessing is strictly worse."""
    server, error = _call([(429, {"retry-after": "3"}), (200, None)])
    assert error is None
    gap = server.hits[1][0] - server.hits[0][0]
    # >= 3 because we honour it; < 6 because jitter is bounded, not unbounded.
    assert 3.0 <= gap < 6.0, f"waited {gap:.1f}s, server asked for 3s"


def test_gives_up_and_stays_bounded():
    """A permanently sick upstream must fail the call, not hang the run."""
    started = time.monotonic()
    server, error = _call([(503, None)])
    elapsed = time.monotonic() - started
    assert isinstance(error, LLMTransient)
    assert len(server.hits) == 6
    # The Modal function timeout is 900s; one call must not approach it.
    assert elapsed < 260, f"took {elapsed:.0f}s"
