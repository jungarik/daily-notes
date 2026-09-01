"""Database adapter for the enrichment specialist.

Context reads (path/tag vocabulary, similar notes, user language), the writes the
agent's tools perform (create note + chunks, move, set metadata),
and thread state for the write-confirmation flow (over the shared chat_threads
table). Higher-level graph/API/helper modules hold the logic that calls these.
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


# ----- context reads -----

def list_paths(user_id: int, limit: int = 30) -> list[tuple[str, int]]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT path, count(*) AS c FROM notes
            WHERE user_id = %s AND path IS NOT NULL AND path <> ''
            GROUP BY path ORDER BY c DESC, path LIMIT %s;
            """,
            (user_id, limit),
        )
        return [(r[0], r[1]) for r in cur.fetchall()]


def list_tags(user_id: int, limit: int = 30) -> list[tuple[str, int]]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT g, count(*) AS c
            FROM notes, jsonb_array_elements_text(tags) AS g
            WHERE user_id = %s GROUP BY g ORDER BY c DESC, g LIMIT %s;
            """,
            (user_id, limit),
        )
        return [(r[0], r[1]) for r in cur.fetchall()]


def similar_notes(user_id: int, query_embedding: str, exclude_note_id: int,
                  limit: int = 5) -> list[dict]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT m.id, m.note_type, m.title, m.path, m.tags,
                   MIN(mc.embedding <=> %s::vector) AS distance
            FROM note_chunks mc JOIN notes m ON m.id = mc.note_id
            WHERE m.user_id = %s AND m.id <> %s AND m.title IS NOT NULL
            GROUP BY m.id, m.note_type, m.title, m.path, m.tags
            ORDER BY distance LIMIT %s;
            """,
            (query_embedding, user_id, exclude_note_id, limit),
        )
        return [{"note_id": r[0], "note_type": r[1], "title": r[2],
                 "path": r[3], "tags": r[4], "distance": float(r[5])}
                for r in cur.fetchall()]


def related_notes(user_id: int, query_embedding: str, limit: int = 5) -> list[dict]:
    """Return user-owned notes that may be linked to a new captured thought."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT n.id, n.note_type, n.title, n.path, n.tags,
                   MIN(c.embedding <=> %s::vector) AS distance
            FROM note_chunks c JOIN notes n ON n.id = c.note_id
            WHERE n.user_id = %s AND n.title IS NOT NULL
            GROUP BY n.id, n.note_type, n.title, n.path, n.tags
            ORDER BY distance LIMIT %s;
            """,
            (query_embedding, user_id, limit),
        )
        return [{"note_id": r[0], "note_type": r[1], "title": r[2],
                 "path": r[3], "tags": r[4] or [], "distance": float(r[5])}
                for r in cur.fetchall()]


def get_language(user_id: int) -> str | None:
    """The user's raw stored language code, or None. The domain normalizes it."""
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


def get_text(note_id: int) -> str | None:
    with cursor() as cur:
        cur.execute("SELECT text FROM notes WHERE id = %s;", (note_id,))
        row = cur.fetchone()
        return row[0] if row else None


def get_meta(note_id: int) -> dict | None:
    with cursor() as cur:
        cur.execute(
            "SELECT note_type, title, path, tags, priority FROM notes WHERE id = %s;", (note_id,))
        row = cur.fetchone()
        if not row:
            return None
        return {"type": row[0], "title": row[1], "path": row[2],
                "tags": row[3] or [], "priority": row[4]}


# ----- writes -----

def save_note(user_id: int, text: str) -> int:
    with cursor() as cur:
        cur.execute(
            "INSERT INTO notes (user_id, text, source_type) VALUES (%s, %s, 'text') RETURNING id;",
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


def set_path(note_id: int, path: str) -> None:
    with cursor() as cur:
        cur.execute("UPDATE notes SET path = %s WHERE id = %s;", (path, note_id))


def set_metadata(note_id, note_type, title, priority, tags, path) -> None:
    with cursor() as cur:
        cur.execute(
            """
            UPDATE notes SET note_type = %s, title = %s, priority = %s, tags = %s, path = %s
            WHERE id = %s;
            """,
            (note_type, title, priority, Json(tags or []), path, note_id),
        )


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
