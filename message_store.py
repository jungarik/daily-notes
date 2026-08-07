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
