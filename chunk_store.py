"""Persistence for note chunks (embedded pieces of a note)."""

from psycopg.types.json import Json

from db import cursor


def save_chunks(note_id: int, chunks: list[dict]) -> None:
    """Insert the chunks belonging to a note.

    Each chunk is a dict: {index, content, token_count, metadata, embedding}
    where `embedding` is a pgvector-compatible string.
    """
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
                (
                    note_id,
                    ch["index"],
                    ch["content"],
                    ch["token_count"],
                    Json(ch["metadata"]),
                    ch["embedding"],
                ),
            )


def similar_notes(user_id: int, query_embedding: str, exclude_note_id: int,
                  limit: int = 5) -> list[dict]:
    """Already-enriched notes most similar to the query embedding (for few-shot).

    Returns [{note_type, title, path, tags}], one per note, closest first.
    Only notes that already have metadata (title set) are useful as examples.
    """
    with cursor() as cur:
        cur.execute(
            """
            SELECT m.note_type, m.title, m.path, m.tags,
                   MIN(mc.embedding <=> %s::vector) AS distance
            FROM note_chunks mc
            JOIN notes m ON m.id = mc.note_id
            WHERE m.user_id = %s AND m.id <> %s AND m.title IS NOT NULL
            GROUP BY m.id, m.note_type, m.title, m.path, m.tags
            ORDER BY distance
            LIMIT %s;
            """,
            (query_embedding, user_id, exclude_note_id, limit),
        )
        return [
            {"note_type": r[0], "title": r[1], "path": r[2], "tags": r[3]}
            for r in cur.fetchall()
        ]


def search_chunks(
    user_id: int,
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
        note_id   parent message id
        chunk_id     this chunk's id
        chunk_index  position of the chunk within its message
        chunk_count  total chunks in that message
        source_type  'text' or 'voice'
        created_at   when the note was saved (recency)
        remind_at    the note's next active reminder (in range when filtering), or None
        token_count  approximate tokens in the chunk
        metadata     the chunk's JSONB metadata
    """
    filtering = remind_start is not None and remind_end is not None
    remind_range = "AND r.remind_at >= %s AND r.remind_at < %s" if filtering else ""
    # When filtering, require the note to actually have a reminder in the range.
    where_filter = "AND rem.remind_at IS NOT NULL" if filtering else ""

    params: list = [query_embedding]
    if filtering:
        params += [remind_start, remind_end]
    params += [user_id, limit]

    with cursor() as cur:
        cur.execute(
            f"""
            WITH scored AS (
                SELECT mc.id            AS chunk_id,
                       mc.note_id    AS note_id,
                       mc.content       AS content,
                       mc.chunk_index   AS chunk_index,
                       mc.token_count   AS token_count,
                       mc.metadata      AS metadata,
                       m.source_type    AS source_type,
                       m.created_at     AS created_at,
                       rem.remind_at    AS remind_at,
                       (mc.embedding <=> %s::vector) AS distance
                FROM note_chunks mc
                JOIN notes m ON m.id = mc.note_id
                LEFT JOIN (
                    SELECT r.note_id, MIN(r.remind_at) AS remind_at
                    FROM reminders r
                    WHERE r.status IN ('scheduled', 'postponed')
                      {remind_range}
                    GROUP BY r.note_id
                ) rem ON rem.note_id = mc.note_id
                WHERE m.user_id = %s {where_filter}
                ORDER BY distance
                LIMIT %s
            )
            SELECT s.chunk_id, s.note_id, s.content, s.chunk_index,
                   s.token_count, s.metadata, s.source_type, s.created_at,
                   s.remind_at, s.distance,
                   ROW_NUMBER() OVER (ORDER BY s.distance) AS rank,
                   (SELECT count(*) FROM note_chunks c2
                    WHERE c2.note_id = s.note_id) AS chunk_count
            FROM scored s
            ORDER BY s.distance;
            """,
            tuple(params),
        )
        rows = cur.fetchall()

    hits: list[dict] = []
    top_similarity = None
    for r in rows:
        distance = float(r[9])
        similarity = 1.0 - distance
        if top_similarity is None:
            top_similarity = similarity
        hits.append(
            {
                "rank": r[10],
                "similarity": round(similarity, 4),
                "distance": round(distance, 4),
                "rel_to_top": round(top_similarity - similarity, 4),
                "content": r[2],
                "note_id": r[1],
                "chunk_id": r[0],
                "chunk_index": r[3],
                "chunk_count": r[11],
                "source_type": r[6],
                "created_at": r[7],
                "remind_at": r[8],
                "token_count": r[4],
                "metadata": r[5],
            }
        )
    return hits
