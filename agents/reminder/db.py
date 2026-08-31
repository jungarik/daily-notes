"""Persistence owned by the reminder agent."""

from psycopg.types.json import Json

from db import cursor


def get_note_for_user(user_id: int, note_id: int) -> dict | None:
    with cursor() as cur:
        cur.execute(
            "SELECT id, title, text, path FROM notes WHERE id = %s AND user_id = %s;",
            (note_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"note_id": row[0], "title": row[1], "text": row[2], "path": row[3]}


def attach_reminder(user_id: int, note_id: int, remind_at) -> int | None:
    """Attach only when the target note belongs to the same user."""
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO reminders (note_id, user_id, remind_at)
            SELECT id, %s, %s FROM notes WHERE id = %s AND user_id = %s
            RETURNING id;
            """,
            (user_id, remind_at, note_id, user_id),
        )
        row = cur.fetchone()
        return row[0] if row else None


def create_note_with_reminder(user_id: int, text: str, chunks: list[dict],
                              remind_at) -> tuple[int, int]:
    """Persist the backing note, chunks, and reminder in one transaction."""
    with cursor() as cur:
        cur.execute(
            "INSERT INTO notes (user_id, text, source_type) VALUES (%s, %s, 'text') RETURNING id;",
            (user_id, text),
        )
        note_id = cur.fetchone()[0]
        for chunk in chunks:
            cur.execute(
                """
                INSERT INTO note_chunks
                    (note_id, chunk_index, content, token_count, metadata, embedding)
                VALUES (%s, %s, %s, %s, %s, %s::vector);
                """,
                (note_id, chunk["index"], chunk["content"], chunk["token_count"],
                 Json(chunk["metadata"]), chunk["embedding"]),
            )
        cur.execute(
            "INSERT INTO reminders (note_id, user_id, remind_at) VALUES (%s, %s, %s) RETURNING id;",
            (note_id, user_id, remind_at),
        )
        return note_id, cur.fetchone()[0]
