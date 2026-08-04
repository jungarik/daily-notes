"""Persistence for messages (the note row itself). Chunks live in chunk_store."""

from db import cursor


def save_message(
    chat_id: int,
    username: str,
    text: str,
    source_type: str = "text",
    audio: bytes | None = None,
    audio_mime: str | None = None,
) -> int:
    """Insert a message row and return its id.

    For voice notes, pass source_type='voice' plus the raw audio bytes and MIME
    type. Chunks are saved separately via chunk_store.save_chunks(message_id, ...).
    """
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO messages (chat_id, username, text, source_type, audio, audio_mime)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (chat_id, username, text, source_type, audio, audio_mime),
        )
        return cur.fetchone()[0]
