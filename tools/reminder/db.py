"""Persistence the reminder agent owns.

Duplicated from the enrich vertical on purpose: each vertical owns the rows
it writes, so one agent's schema decisions cannot ripple into another.
"""

from psycopg.types.json import Json

from db import cursor


def attach_reminder(user_id: int, note_id: int, remind_at) -> int | None:
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO reminders (note_id, user_id, remind_at)
            SELECT id, %s, %s FROM notes WHERE id = %s AND user_id = %s
            RETURNING id;
            """, (user_id, remind_at, note_id, user_id))
        row = cur.fetchone()
        return row[0] if row else None


def get_note_for_user(user_id: int, note_id: int) -> dict | None:
    with cursor() as cur:
        cur.execute(
            """
            SELECT id, text, title, path, tags, note_type, priority
            FROM notes WHERE id = %s AND user_id = %s;
            """,
            (note_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "text": row[1], "title": row[2], "path": row[3],
                "tags": row[4] or [], "type": row[5], "priority": row[6]}


def save_note(user_id: int, text: str) -> int:
    with cursor() as cur:
        cur.execute(
            "INSERT INTO notes (user_id, text, source_type) "
            "VALUES (%s, %s, 'text') RETURNING id;",
            (user_id, text),
        )
        return cur.fetchone()[0]


def save_chunks(note_id: int, chunks: list[dict]) -> None:
    if not chunks:
        return
    with cursor() as cur:
        for ch in chunks:
            cur.execute(
                """
                INSERT INTO note_chunks
                    (note_id, chunk_index, content, token_count, metadata, embedding)
                VALUES (%s, %s, %s, %s, %s, %s::vector);
                """,
                (note_id, ch["index"], ch["content"], ch["token_count"],
                 Json(ch["metadata"]), ch["embedding"]),
            )
