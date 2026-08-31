"""Persistence for the enrichment agent (isolated SQL).

The agent's raw queries — path/tag vocabulary, similar-note lookup, metadata
write, and the user's stored language — over the shared `db.cursor`. `domain.py`
holds the logic that calls these; no SQL lives outside this file.
"""

from psycopg.types.json import Json

from db import cursor


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


def set_metadata(note_id, note_type, title, priority, tags, path) -> None:
    with cursor() as cur:
        cur.execute(
            """
            UPDATE notes SET note_type = %s, title = %s, priority = %s, tags = %s, path = %s
            WHERE id = %s;
            """,
            (note_type, title, priority, Json(tags or []), path, note_id),
        )


def similar_notes(user_id: int, query_embedding: str, exclude_note_id: int,
                  limit: int = 5) -> list[dict]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT m.note_type, m.title, m.path, m.tags,
                   MIN(mc.embedding <=> %s::vector) AS distance
            FROM note_chunks mc JOIN notes m ON m.id = mc.note_id
            WHERE m.user_id = %s AND m.id <> %s AND m.title IS NOT NULL
            GROUP BY m.id, m.note_type, m.title, m.path, m.tags
            ORDER BY distance LIMIT %s;
            """,
            (query_embedding, user_id, exclude_note_id, limit),
        )
        return [{"note_type": r[0], "title": r[1], "path": r[2], "tags": r[3],
                 "distance": float(r[4])} for r in cur.fetchall()]


def get_language(user_id: int) -> str | None:
    """The user's raw stored language code, or None. The domain normalizes it."""
    with cursor() as cur:
        cur.execute("SELECT language FROM users WHERE id = %s;", (user_id,))
        row = cur.fetchone()
        return row[0] if row else None
