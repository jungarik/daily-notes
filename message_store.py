"""Persistence for messages (the note row itself). Chunks live in chunk_store."""

from psycopg.types.json import Json

from db import cursor


def save_message(
    chat_id: int,
    username: str,
    text: str,
    source_type: str = "text",
    audio_key: str | None = None,
    audio_mime: str | None = None,
    note_type: str | None = None,
    title: str | None = None,
    priority: str | None = None,
    tags: list | None = None,
    projects: list | None = None,
) -> int:
    """Insert a message row (with enrichment metadata) and return its id.

    For voice notes, pass source_type='voice' plus the object-storage key of the
    uploaded audio and its MIME type. Chunks are saved separately via
    chunk_store.save_chunks(message_id, ...).
    """
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO messages
                (chat_id, username, text, source_type, audio_key, audio_mime,
                 note_type, title, priority, tags, projects)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (
                chat_id, username, text, source_type, audio_key, audio_mime,
                note_type, title, priority, Json(tags or []), Json(projects or []),
            ),
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
    projects: list | None,
) -> None:
    """Fill in enrichment metadata for a message (deferred/on-demand pass)."""
    with cursor() as cur:
        cur.execute(
            """
            UPDATE messages
            SET note_type = %s, title = %s, priority = %s, tags = %s, projects = %s
            WHERE id = %s;
            """,
            (note_type, title, priority, Json(tags or []), Json(projects or []), message_id),
        )


def list_projects(chat_id: int, limit: int = 20) -> list[str]:
    """The chat's existing project names, most-used first (controlled vocabulary)."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT p, count(*) AS c
            FROM messages, jsonb_array_elements_text(projects) AS p
            WHERE chat_id = %s
            GROUP BY p ORDER BY c DESC, p
            LIMIT %s;
            """,
            (chat_id, limit),
        )
        return [row[0] for row in cur.fetchall()]


def list_tags(chat_id: int, limit: int = 30) -> list[str]:
    """The chat's existing tags, most-used first (controlled vocabulary)."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT g, count(*) AS c
            FROM messages, jsonb_array_elements_text(tags) AS g
            WHERE chat_id = %s
            GROUP BY g ORDER BY c DESC, g
            LIMIT %s;
            """,
            (chat_id, limit),
        )
        return [row[0] for row in cur.fetchall()]
