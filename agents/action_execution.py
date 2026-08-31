"""Idempotency ledger for user-confirmed agent writes.

The unique action id is claimed before a write runs. Its result is checkpointed
immediately after the write, before the graph asks the model for a conversational
reply. Retries therefore reuse the stored result instead of repeating the write.
"""

from collections.abc import Callable

from psycopg.types.json import Json

from db import cursor


def claim(action_id: str, user_id: int, agent: str, action: dict) -> dict:
    """Atomically claim an action, or return its existing execution record."""
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO action_executions (action_id, user_id, agent, action, status)
            VALUES (%s, %s, %s, %s, 'executing')
            ON CONFLICT (action_id) DO NOTHING
            RETURNING action_id;
            """,
            (action_id, user_id, agent, Json(action)),
        )
        if cur.fetchone():
            return {"status": "claimed"}

        cur.execute(
            """
            SELECT user_id, agent, action, status, result, error
            FROM action_executions WHERE action_id = %s;
            """,
            (action_id,),
        )
        row = cur.fetchone()

    if row is None:
        raise RuntimeError("Action claim disappeared")
    if row[0] != user_id or row[1] != agent or row[2] != action:
        raise RuntimeError("Action id is already associated with different action data")
    return {"status": row[3], "result": row[4], "error": row[5]}


def complete(action_id: str, user_id: int, result: str) -> None:
    """Persist a successful tool result before any later model call."""
    with cursor() as cur:
        cur.execute(
            """
            UPDATE action_executions
            SET status = 'completed', result = %s, error = NULL,
                completed_at = now(), updated_at = now()
            WHERE action_id = %s AND user_id = %s AND status = 'executing';
            """,
            (result, action_id, user_id),
        )
        if cur.rowcount != 1:
            raise RuntimeError("Action execution could not be completed")


def fail(action_id: str, user_id: int, error: str) -> None:
    """Record an uncertain/failed attempt; it must not be retried automatically."""
    with cursor() as cur:
        cur.execute(
            """
            UPDATE action_executions
            SET status = 'failed', error = %s, updated_at = now()
            WHERE action_id = %s AND user_id = %s AND status = 'executing';
            """,
            (error, action_id, user_id),
        )


def execute_once(action_id: str, user_id: int, agent: str, action: dict,
                 execute: Callable[[], str]) -> str:
    """Execute a confirmed write at most once and return a durable result."""
    record = claim(action_id, user_id, agent, action)
    if record["status"] == "completed":
        return record["result"] or "The action was already completed."
    if record["status"] == "executing":
        return "This action is already being processed; do not perform it again."
    if record["status"] == "failed":
        detail = record.get("error") or "unknown error"
        return f"This action was already attempted and was not retried: {detail}"

    try:
        result = str(execute())
    except Exception as exc:
        fail(action_id, user_id, str(exc))
        raise
    complete(action_id, user_id, result)
    return result
