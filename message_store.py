"""Persistence for messages (the note row itself). Chunks live in chunk_store."""

from psycopg.types.json import Json

from db import cursor


def save_message(
    user_id: int,
    username: str,
    text: str,
    source_type: str = "text",
    audio_key: str | None = None,
    audio_mime: str | None = None,
) -> int:
    """Insert a message row and return its id.

    Enrichment metadata (type/title/priority/tags/path) is filled later, on
    demand, via set_metadata(). For voice notes pass source_type='voice' plus the
    object-storage key of the uploaded audio and its MIME type.
    """
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO messages (user_id, username, text, source_type, audio_key, audio_mime)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (user_id, username, text, source_type, audio_key, audio_mime),
        )
        return cur.fetchone()[0]


def get_text(message_id: int) -> str | None:
    """Return a message's text, or None."""
    with cursor() as cur:
        cur.execute("SELECT text FROM messages WHERE id = %s;", (message_id,))
        row = cur.fetchone()
        return row[0] if row else None


def set_metadata(
    message_id: int,
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
            UPDATE messages
            SET note_type = %s, title = %s, priority = %s, tags = %s, path = %s
            WHERE id = %s;
            """,
            (note_type, title, priority, Json(tags or []), path, message_id),
        )


def list_paths(user_id: int, limit: int = 30) -> list[str]:
    """The user's existing vault paths, most-used first (controlled vocabulary)."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT path, count(*) AS c
            FROM messages
            WHERE user_id = %s AND path IS NOT NULL AND path <> ''
            GROUP BY path ORDER BY c DESC, path
            LIMIT %s;
            """,
            (user_id, limit),
        )
        return [row[0] for row in cur.fetchall()]


def list_tags(user_id: int, limit: int = 30) -> list[str]:
    """The user's existing tags, most-used first (controlled vocabulary)."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT g, count(*) AS c
            FROM messages, jsonb_array_elements_text(tags) AS g
            WHERE user_id = %s
            GROUP BY g ORDER BY c DESC, g
            LIMIT %s;
            """,
            (user_id, limit),
        )
        return [row[0] for row in cur.fetchall()]
