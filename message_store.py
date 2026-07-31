"""Persistence for messages and their chunks (no business logic)."""

from psycopg.types.json import Json

from db import cursor


def save_message(
    chat_id: int,
    username: str,
    text: str,
    chunks: list[dict],
    source_type: str = "text",
    audio: bytes | None = None,
    audio_mime: str | None = None,
) -> int:
    """Insert a message and its pre-computed chunks in one transaction.

    Each chunk is a dict: {index, content, token_count, metadata, embedding}
    where `embedding` is a pgvector-compatible string. Returns the message id.
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
        message_id = cur.fetchone()[0]
        for ch in chunks:
            cur.execute(
                """
                INSERT INTO message_chunks
                    (message_id, chunk_index, content, token_count, metadata, embedding)
                VALUES (%s, %s, %s, %s, %s, %s::vector);
                """,
                (
                    message_id,
                    ch["index"],
                    ch["content"],
                    ch["token_count"],
                    Json(ch["metadata"]),
                    ch["embedding"],
                ),
            )
        return message_id


def search_chunks(chat_id: int, query_embedding: str, limit: int = 5):
    """Return notes whose closest chunk best matches the query embedding.

    [(text, created_at, distance)] deduped to one row per message.
    """
    with cursor() as cur:
        cur.execute(
            """
            SELECT m.text, m.created_at, MIN(mc.embedding <=> %s::vector) AS distance
            FROM message_chunks mc
            JOIN messages m ON m.id = mc.message_id
            WHERE m.chat_id = %s
            GROUP BY m.id, m.text, m.created_at
            ORDER BY distance
            LIMIT %s;
            """,
            (query_embedding, chat_id, limit),
        )
        return cur.fetchall()
