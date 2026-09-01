"""Database adapter for Enrich API state and fast-capture persistence."""

from psycopg.types.json import Json

from db import cursor


def get_language(user_id: int) -> str | None:
    with cursor() as cur:
        cur.execute("SELECT language FROM users WHERE id = %s;", (user_id,))
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


def save_captured_thought(user_id: int, text: str, metadata: dict,
                          chunks: list[dict], linked_note_ids: list[int]) -> dict:
    """Persist a captured thought, its chunks, metadata and links atomically."""
    linked_note_ids = list(dict.fromkeys(linked_note_ids))
    with cursor() as cur:
        if linked_note_ids:
            cur.execute(
                "SELECT id FROM notes WHERE user_id = %s AND id = ANY(%s);",
                (user_id, linked_note_ids),
            )
            owned_ids = {row[0] for row in cur.fetchall()}
            if owned_ids != set(linked_note_ids):
                raise ValueError("Every linked note must belong to the user")

        cur.execute(
            """
            INSERT INTO notes
                (user_id, text, source_type, note_type, title, priority, tags, path)
            VALUES (%s, %s, 'text', %s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (user_id, text, metadata["type"], metadata["title"],
             metadata["priority"], Json(metadata["tags"]), metadata["path"]),
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
        for linked_note_id in linked_note_ids:
            cur.execute(
                """
                INSERT INTO note_links (from_note_id, to_note_id, kind, source)
                VALUES (%s, %s, 'related', 'user')
                ON CONFLICT (from_note_id, to_note_id) DO NOTHING;
                """,
                (note_id, linked_note_id),
            )
    return {"note_id": note_id, "linked_note_ids": linked_note_ids}


# ----- thread state (shared chat_threads table) -----

def create_thread(user_id: int) -> int:
    with cursor() as cur:
        cur.execute("INSERT INTO chat_threads (user_id) VALUES (%s) RETURNING id;", (user_id,))
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
            "UPDATE chat_threads SET messages = %s, pending = %s, updated_at = now() WHERE id = %s;",
            (Json(messages), Json(pending) if pending is not None else None, thread_id),
        )
