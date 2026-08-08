"""Content Poster graph assembly.

    preflight -> write -> render -> publish -> notify

A straight line, because the work is one. What the graph provides is durability:
`durability="sync"` writes the checkpoint **before** each irreversible step, so a
container killed mid-run resumes instead of restarting. A checkpoint written
after an irreversible action cannot prevent repeating it — and the irreversible
action here is a public post.

Retry policy differs by node for the same reason as elsewhere: writing is worth
retrying (the proxy has 502 spells), publishing is not (a retry past the
idempotency claim is exactly what the claim exists to prevent, and the claim
already handles the safe case).
"""
from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from graph.nodes import (
    make_notify,
    make_preflight,
    make_publish,
    make_reader,
    make_render,
    make_write,
)
from graph.state import PosterState

log = logging.getLogger("content_poster.graph.build")


def build_graph(config, budget, checkpointer=None, forced=None):
    reader = make_reader(config)
    graph = StateGraph(PosterState)

    graph.add_node(
        "preflight",
        make_preflight(config, reader, forced),
        # The site repo read can blip; everything downstream depends on it.
        retry_policy=RetryPolicy(max_attempts=3, initial_interval=3.0, backoff_factor=2.0),
    )
    graph.add_node(
        "write",
        make_write(config, budget, reader),
        # The proxy has intermittent 502 spells that clear within a minute or
        # two, and 30-70s calls are normal. Be patient rather than give up.
        retry_policy=RetryPolicy(max_attempts=3, initial_interval=8.0, backoff_factor=2.0),
    )
    graph.add_node(
        "render",
        make_render(config),
        retry_policy=RetryPolicy(max_attempts=2, initial_interval=5.0),
    )
    # No retry_policy on publish. Every publish is already wrapped in an
    # idempotency claim, and a node-level retry would re-enter that claim and be
    # refused — so the retry could only ever turn a clean skip into noise.
    graph.add_node("publish", make_publish(config))
    graph.add_node("notify", make_notify(config))

    graph.add_edge(START, "preflight")
    graph.add_conditional_edges(
        "preflight",
        # Nothing due is the common case: the calendar has 17 slots across a
        # week and this runs hourly. Short-circuiting keeps a quiet hour from
        # costing an LLM call.
        lambda state: "write" if state.get("due") else "notify",
        {"write": "write", "notify": "notify"},
    )
    graph.add_edge("write", "render")
    graph.add_edge("render", "publish")
    graph.add_edge("publish", "notify")
    graph.add_edge("notify", END)

    return graph.compile(checkpointer=checkpointer)


def make_checkpointer(config):
    """PostgresSaver in this agent's own schema (`cp_ckpt`).

    Per-agent schema is load-bearing: PostgresSaver keys rows by `thread_id`
    alone, so two agents sharing a schema would resume each other's runs on any
    collision.

    Unlike the Lead Finder, a missing checkpointer here is worth complaining
    loudly about — this agent takes irreversible actions, and resumability is
    part of how a killed container avoids repeating one. It still does not abort
    the run, because `core.external_actions` is the real duplicate guard.
    """
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg import Connection

        conn = Connection.connect(
            config.database_url,
            autocommit=True,
            prepare_threshold=0,
            options=f"-c search_path={config.checkpoint_schema},public",
        )
        saver = PostgresSaver(conn)
        saver.setup()
        log.info("checkpointer ready in schema %s", config.checkpoint_schema)
        return saver
    except Exception:
        log.error(
            "checkpointer unavailable - running WITHOUT resumability. "
            "core.external_actions still prevents duplicate posts.",
            exc_info=True,
        )
        return None
