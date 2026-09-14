"""Persistence for the chat section (isolated): caller settings and thread state.

This section owns the `chat_threads` projection (migration 0019) — the running
message list plus any handed-off action awaiting confirmation. The conversation
agent runs the graph over data this section loads, and returns the result for
this section to persist.
"""

from psycopg.types.json import Json

from db import cursor


def get_settings(user_id: int) -> tuple[str | None, str | None]:
    """(timezone, language) for a user, (None, None) if absent."""
    with cursor() as cur:
        cur.execute("SELECT timezone, language FROM users WHERE id = %s;", (user_id,))
        row = cur.fetchone()
        return (row[0], row[1]) if row else (None, None)


def create_thread(user_id: int) -> int:
    with cursor() as cur:
        cur.execute("INSERT INTO chat_threads (user_id) VALUES (%s) RETURNING id;",
                    (user_id,))
        return cur.fetchone()[0]


def get_thread(user_id: int, thread_id: int) -> dict | None:
    with cursor() as cur:
        cur.execute(
            "SELECT id, messages, pending FROM chat_threads WHERE id = %s AND user_id = %s;",
            (thread_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "messages": row[1] or [], "pending": row[2]}


def save_thread(thread_id: int, messages: list, pending: dict | None) -> None:
    with cursor() as cur:
        cur.execute(
            "UPDATE chat_threads SET messages = %s, pending = %s, updated_at = now() "
            "WHERE id = %s;",
            (Json(messages), Json(pending) if pending is not None else None, thread_id),
        )
