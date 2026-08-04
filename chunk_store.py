"""Persistence for message chunks (embedded pieces of a message)."""

from psycopg.types.json import Json

from db import cursor


def save_chunks(message_id: int, chunks: list[dict]) -> None:
    """Insert the chunks belonging to a message.

    Each chunk is a dict: {index, content, token_count, metadata, embedding}
    where `embedding` is a pgvector-compatible string.
    """
    if not chunks:
        return
    with cursor() as cur:
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
