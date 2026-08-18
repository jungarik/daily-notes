"""Persistence for notes (the note row itself). Chunks live in chunk_store."""

from psycopg.types.json import Json

from db import cursor


def save_note(
    user_id: int,
    text: str,
    source_type: str = "text",
    audio_key: str | None = None,
    audio_mime: str | None = None,
) -> int:
    """Insert a note row and return its id.

    The sender's username lives on the users row, not here. Enrichment metadata
    (type/title/priority/tags/path) is filled later, on demand, via
    set_metadata(). For voice notes pass source_type='voice' plus the
    object-storage key of the uploaded audio and its MIME type.
    """
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO notes (user_id, text, source_type, audio_key, audio_mime)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (user_id, text, source_type, audio_key, audio_mime),
        )
        return cur.fetchone()[0]


def delete_if_bare(note_id: int) -> bool:
    """Delete a note only if it has no enrichment metadata (no path), no links and
    no active reminder — a guard against accidentally discarding notes the user has
    invested in (an active reminder would otherwise be silently cascade-deleted).
    Chunks, links and reminders all cascade (FK ON DELETE CASCADE) once deletion
    proceeds. Returns True if the row was deleted, False if the guard blocked it
    (or the note didn't exist)."""
    with cursor() as cur:
        cur.execute(
            """
            DELETE FROM notes
            WHERE id = %s
              AND path IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM note_links l
                  WHERE l.from_note_id = %s OR l.to_note_id = %s
              )
              AND NOT EXISTS (
                  SELECT 1 FROM reminders r
                  WHERE r.note_id = %s AND r.status IN ('scheduled', 'postponed')
              )
            RETURNING id;
            """,
            (note_id, note_id, note_id, note_id),
        )
        return cur.fetchone() is not None


def set_text(note_id: int, text: str) -> None:
    """Overwrite a note's text (e.g. after a polish pass). Chunks are rebuilt
    separately by the caller so embeddings stay in sync."""
    with cursor() as cur:
        cur.execute("UPDATE notes SET text = %s WHERE id = %s;", (text, note_id))


def get_text(note_id: int) -> str | None:
    """Return a note's text, or None."""
    with cursor() as cur:
        cur.execute("SELECT text FROM notes WHERE id = %s;", (note_id,))
        row = cur.fetchone()
        return row[0] if row else None


def get_note(note_id: int) -> dict | None:
    """Return {text, title, path, tags} for a note, or None."""
    with cursor() as cur:
        cur.execute(
            "SELECT text, title, path, tags FROM notes WHERE id = %s;", (note_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"text": row[0], "title": row[1], "path": row[2], "tags": row[3]}


def get_note_for_user(user_id: int, note_id: int) -> dict | None:
    """Full note detail scoped to an owner (for the web-app preview). Returns None
    if the note doesn't exist or belongs to someone else."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT id, text, title, path, tags, note_type, source_type, created_at
            FROM notes WHERE id = %s AND user_id = %s;
            """,
            (note_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0], "text": row[1], "title": row[2], "path": row[3],
            "tags": row[4] or [], "type": row[5], "source_type": row[6],
            "created_at": row[7],
        }


def set_metadata(
    note_id: int,
    note_type: str | None,
    title: str | None,
    priority: str | None,
    tags: list | None,
    path: str | None,
) -> None:
    """Fill in enrichment metadata for a message (deferred/on-demand pass)."""
    with cursor() as cur:
        cur.execute(
            """
            UPDATE notes
            SET note_type = %s, title = %s, priority = %s, tags = %s, path = %s
            WHERE id = %s;
            """,
            (note_type, title, priority, Json(tags or []), path, note_id),
        )


def get_meta(note_id: int) -> dict | None:
    """Return the full enrichment metadata {type, title, path, tags, priority}
    for a note, or None if it doesn't exist."""
    with cursor() as cur:
        cur.execute(
            "SELECT note_type, title, path, tags, priority FROM notes WHERE id = %s;",
            (note_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "type": row[0], "title": row[1], "path": row[2],
            "tags": row[3] or [], "priority": row[4],
        }


def set_path(note_id: int, path: str) -> None:
    """Update just a note's vault path (leaves other metadata untouched)."""
    with cursor() as cur:
        cur.execute(
            "UPDATE notes SET path = %s WHERE id = %s;", (path, note_id)
        )


def list_notes(user_id: int, limit: int = 2000) -> list[dict]:
    """All of a user's notes for the browser: [{id, title, path, text, links}],
    newest first. `title` may be None (not enriched) — the caller supplies a
    fallback. `links` is how many links the note participates in (either direction)."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT n.id, n.title, n.path, n.text,
                   (SELECT count(*) FROM note_links l
                    WHERE l.from_note_id = n.id OR l.to_note_id = n.id) AS links
            FROM notes n
            WHERE n.user_id = %s
            ORDER BY n.id DESC
            LIMIT %s;
            """,
            (user_id, limit),
        )
        return [
            {"id": r[0], "title": r[1], "path": r[2], "text": r[3], "links": r[4]}
            for r in cur.fetchall()
        ]


def list_paths(user_id: int, limit: int = 30) -> list[tuple[str, int]]:
    """The user's existing vault paths with note counts, most-used first."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT path, count(*) AS c
            FROM notes
            WHERE user_id = %s AND path IS NOT NULL AND path <> ''
            GROUP BY path ORDER BY c DESC, path
            LIMIT %s;
            """,
            (user_id, limit),
        )
        return [(row[0], row[1]) for row in cur.fetchall()]


def list_tags(user_id: int, limit: int = 30) -> list[tuple[str, int]]:
    """The user's existing tags with usage counts, most-used first."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT g, count(*) AS c
            FROM notes, jsonb_array_elements_text(tags) AS g
            WHERE user_id = %s
            GROUP BY g ORDER BY c DESC, g
            LIMIT %s;
            """,
            (user_id, limit),
        )
        return [(row[0], row[1]) for row in cur.fetchall()]
