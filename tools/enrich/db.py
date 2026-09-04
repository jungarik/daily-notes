"""Database adapter used only by Enrich tool handlers and tool validation."""

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


def link_candidates(user_id: int, query_embedding: str, exclude_note_id: int,
                    limit: int) -> list[dict]:
    """Nearest neighbours plus a text snippet, as input for idea-level ranking.

    Same recall as `similar_notes`, but carries enough of each note's body for a
    model to judge which idea it shares with the source note.
    """
    with cursor() as cur:
        cur.execute(
            """
            SELECT m.id, m.note_type, m.title, m.path, m.tags,
                   LEFT(m.text, 400) AS snippet,
                   MIN(mc.embedding <=> %s::vector) AS distance
            FROM note_chunks mc JOIN notes m ON m.id = mc.note_id
            WHERE m.user_id = %s AND m.id <> %s AND m.title IS NOT NULL
            GROUP BY m.id, m.note_type, m.title, m.path, m.tags, m.text
            ORDER BY distance LIMIT %s;
            """,
            (query_embedding, user_id, exclude_note_id, limit),
        )

        return [{"note_id": r[0], "note_type": r[1], "title": r[2],
                 "path": r[3], "tags": r[4] or [], "snippet": r[5],
                 "distance": float(r[6])} for r in cur.fetchall()]


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


def owned_note_ids(user_id: int, note_ids: list[int]) -> set[int]:
    """Return the subset of note_ids that belong to the user."""
    if not note_ids:
        return set()

    with cursor() as cur:
        cur.execute(
            "SELECT id FROM notes WHERE user_id = %s AND id = ANY(%s);",
            (user_id, list(note_ids)),
        )

        return {row[0] for row in cur.fetchall()}


def create_links(from_note_id: int, to_note_ids: list[int]) -> list[int]:
    """Insert directed related-links from one note to each target. Skips
    self-links and existing edges (note_links is read as bidirectional)."""
    linked = []

    with cursor() as cur:
        for to_note_id in to_note_ids:
            if to_note_id == from_note_id:
                continue

            cur.execute(
                """
                INSERT INTO note_links (from_note_id, to_note_id, kind, source)
                VALUES (%s, %s, 'related', 'user')
                ON CONFLICT (from_note_id, to_note_id) DO NOTHING;
                """,
                (from_note_id, to_note_id),
            )
            linked.append(to_note_id)

    return linked


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


def get_meta(note_id: int) -> dict | None:
    with cursor() as cur:
        cur.execute(
            "SELECT note_type, title, path, tags, priority FROM notes WHERE id = %s;",
            (note_id,))
        row = cur.fetchone()
        if not row:
            return None
        return {"type": row[0], "title": row[1], "path": row[2],
                "tags": row[3] or [], "priority": row[4]}


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


def set_path(note_id: int, path: str) -> None:
    with cursor() as cur:
        cur.execute("UPDATE notes SET path = %s WHERE id = %s;", (path, note_id))


def set_tags(note_id: int, tags: list[str]) -> None:
    with cursor() as cur:
        cur.execute("UPDATE notes SET tags = %s WHERE id = %s;",
                    (Json(tags or []), note_id))


def set_metadata(note_id, note_type, title, priority, tags, path) -> None:
    with cursor() as cur:
        cur.execute(
            """
            UPDATE notes SET note_type = %s, title = %s, priority = %s, tags = %s, path = %s
            WHERE id = %s;
            """,
            (note_type, title, priority, Json(tags or []), path, note_id),
        )
