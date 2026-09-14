"""PostgreSQL-backed LangGraph runtime checkpoint sessions.

The saver owns LangGraph's standard checkpoint tables. Application migrations
still own business tables; ``setup()`` is called once during API startup.
"""

from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import Connection
from psycopg.rows import dict_row

import config


def _connect():
    return Connection.connect(
        config.DATABASE_URL,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )


def _saver(conn) -> PostgresSaver:
    # State is deliberately JSON/msgpack-safe. Do not allow arbitrary classes
    # to be reconstructed from a compromised checkpoint database.
    
    return PostgresSaver(conn, serde=JsonPlusSerializer(allowed_msgpack_modules=None))


def setup() -> None:
    """Create/upgrade the standard LangGraph checkpoint schema."""
    with _connect() as conn:
        _saver(conn).setup()


@contextmanager
def saver_session():
    """Scope a durable checkpoint saver to one open connection."""
    with _connect() as conn:
        yield _saver(conn)


def graph_config(namespace: str, thread_id, max_steps: int) -> dict:
    """The LangGraph config for one run: which thread it belongs to, and how far
    it may travel. A step may take a tool or approve edge as well as its own, so
    the budget is widened into graph hops."""
    return {
        "configurable": {
            "thread_id": f"{namespace}:{thread_id}",
        },
        "recursion_limit": max(20, max_steps * 3 + 5),
    }


def has_interrupts(tasks) -> bool:
    """True when any pending task is parked on an interrupt (awaiting approval)."""
    return any(task.interrupts for task in tasks)
