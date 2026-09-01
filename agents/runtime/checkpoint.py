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
    serializer = JsonPlusSerializer(allowed_msgpack_modules=None)
    return PostgresSaver(conn, serde=serializer)


def setup() -> None:
    """Create/upgrade the standard LangGraph checkpoint schema."""
    with _connect() as conn:
        _saver(conn).setup()


@contextmanager
def session(build_graph, namespace: str, thread_id: int):
    """Yield a graph compiled with a durable saver and its scoped config."""
    with _connect() as conn:
        graph = build_graph(_saver(conn))
        graph_config = {
            "configurable": {"thread_id": f"{namespace}:{thread_id}"},
        }
        yield graph, graph_config


def is_interrupted(snapshot) -> bool:
    return any(task.interrupts for task in snapshot.tasks)
