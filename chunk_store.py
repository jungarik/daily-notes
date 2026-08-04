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


def search_chunks(
    chat_id: int,
    query_embedding: str,
    limit: int = 5,
    remind_start=None,
    remind_end=None,
) -> list[dict]:
    """Top-k matching chunks with analytics for downstream (LLM) use.

    If `remind_start`/`remind_end` are given, results are restricted to chunks
    whose message has an active reminder due in [remind_start, remind_end) — used
    to answer "what do I have to do today?" style queries.

    Each hit is a dict:
        rank         1-based position in the result set
        similarity   cosine similarity 0..1 (1 - cosine distance)
        distance     raw cosine distance
        rel_to_top   similarity gap behind the #1 hit (0 for the top hit)
        content      the matched chunk text
        message_id   parent message id
        chunk_id     this chunk's id
        chunk_index  position of the chunk within its message
        chunk_count  total chunks in that message
        source_type  'text' or 'voice'
        created_at   when the note was saved (recency)
        token_count  approximate tokens in the chunk
        metadata     the chunk's JSONB metadata
    """
    params: list = [query_embedding, chat_id]
    reminder_filter = ""
    if remind_start is not None and remind_end is not None:
        reminder_filter = """
                  AND EXISTS (
                      SELECT 1 FROM reminders r
                      WHERE r.message_id = mc.message_id
                        AND r.status IN ('scheduled', 'postponed')
                        AND r.remind_at >= %s AND r.remind_at < %s
                  )"""
        params += [remind_start, remind_end]
    params.append(limit)

    with cursor() as cur:
        cur.execute(
            f"""
            WITH scored AS (
                SELECT mc.id            AS chunk_id,
                       mc.message_id    AS message_id,
                       mc.content       AS content,
                       mc.chunk_index   AS chunk_index,
                       mc.token_count   AS token_count,
                       mc.metadata      AS metadata,
                       m.source_type    AS source_type,
                       m.created_at     AS created_at,
                       (mc.embedding <=> %s::vector) AS distance
                FROM message_chunks mc
                JOIN messages m ON m.id = mc.message_id
                WHERE m.chat_id = %s{reminder_filter}
                ORDER BY distance
                LIMIT %s
            )
            SELECT s.chunk_id, s.message_id, s.content, s.chunk_index,
                   s.token_count, s.metadata, s.source_type, s.created_at, s.distance,
                   ROW_NUMBER() OVER (ORDER BY s.distance) AS rank,
                   (SELECT count(*) FROM message_chunks c2
                    WHERE c2.message_id = s.message_id) AS chunk_count
            FROM scored s
            ORDER BY s.distance;
            """,
            tuple(params),
        )
        rows = cur.fetchall()

    hits: list[dict] = []
    top_similarity = None
    for r in rows:
        distance = float(r[8])
        similarity = 1.0 - distance
        if top_similarity is None:
            top_similarity = similarity
        hits.append(
            {
                "rank": r[9],
                "similarity": round(similarity, 4),
                "distance": round(distance, 4),
                "rel_to_top": round(top_similarity - similarity, 4),
                "content": r[2],
                "message_id": r[1],
                "chunk_id": r[0],
                "chunk_index": r[3],
                "chunk_count": r[10],
                "source_type": r[6],
                "created_at": r[7],
                "token_count": r[4],
                "metadata": r[5],
            }
        )
    return hits
