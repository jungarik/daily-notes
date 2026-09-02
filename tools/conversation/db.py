"""Owner-scoped database reads used by Conversation tools."""

from db import cursor


def notes_brief(user_id: int, ids) -> list[dict]:
    ids = list(ids)
    if not ids:
        return []
    with cursor() as cur:
        cur.execute(
            "SELECT id, title, text, path FROM notes WHERE user_id = %s AND id = ANY(%s);",
            (user_id, ids),
        )
        return [{"id": row[0], "title": row[1], "text": row[2], "path": row[3]}
                for row in cur.fetchall()]


def get_note_for_user(user_id: int, note_id: int) -> dict | None:
    with cursor() as cur:
        cur.execute(
            "SELECT id, text, title, path, tags FROM notes WHERE id = %s AND user_id = %s;",
            (note_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "text": row[1], "title": row[2], "path": row[3],
                "tags": row[4] or []}


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
        return [(row[0], row[1]) for row in cur.fetchall()]


def links_of_for_user(user_id: int, note_id: int, limit: int = 100):
    with cursor() as cur:
        cur.execute(
            """
            SELECT n.id, n.title, n.text, 'out' AS direction
            FROM note_links l JOIN notes n ON n.id = l.to_note_id
            WHERE l.from_note_id = %s AND n.user_id = %s
            UNION
            SELECT n.id, n.title, n.text, 'in' AS direction
            FROM note_links l JOIN notes n ON n.id = l.from_note_id
            WHERE l.to_note_id = %s AND n.user_id = %s
            ORDER BY direction LIMIT %s;
            """,
            (note_id, user_id, note_id, user_id, limit),
        )
        return cur.fetchall()


def upcoming_reminders(user_id: int, limit: int = 10):
    with cursor() as cur:
        cur.execute(
            """
            SELECT r.id, r.remind_at, n.text, r.status
            FROM reminders r JOIN notes n ON n.id = r.note_id
            WHERE r.user_id = %s AND r.status IN ('scheduled', 'postponed')
            ORDER BY r.remind_at LIMIT %s;
            """,
            (user_id, limit),
        )
        return cur.fetchall()


def agenda_reminders(user_id: int, start_at, end_at, limit: int = 50) -> list[dict]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT r.id, r.note_id, r.remind_at, n.text, n.title, r.status
            FROM reminders r JOIN notes n ON n.id = r.note_id
            WHERE r.user_id = %s AND r.status IN ('scheduled', 'postponed')
              AND r.remind_at >= %s AND r.remind_at < %s
            ORDER BY r.remind_at LIMIT %s;
            """,
            (user_id, start_at, end_at, limit),
        )
        return [{"reminder_id": row[0], "note_id": row[1], "remind_at": row[2],
                 "text": row[3], "title": row[4], "status": row[5]}
                for row in cur.fetchall()]


def get_user_settings(user_id: int) -> tuple[str | None, str | None]:
    with cursor() as cur:
        cur.execute("SELECT timezone, language FROM users WHERE id = %s;", (user_id,))
        row = cur.fetchone()
        return (row[0], row[1]) if row else (None, None)


def search_chunks(user_id: int, query_embedding: str, limit: int = 5) -> list[dict]:
    with cursor() as cur:
        cur.execute(
            """
            WITH scored AS (
                SELECT c.id AS chunk_id, c.note_id, c.content, c.chunk_index,
                       c.token_count, c.metadata, n.source_type, n.created_at,
                       rem.remind_at, (c.embedding <=> %s::vector) AS distance
                FROM note_chunks c JOIN notes n ON n.id = c.note_id
                LEFT JOIN (
                    SELECT r.note_id, MIN(r.remind_at) AS remind_at FROM reminders r
                    WHERE r.status IN ('scheduled', 'postponed') GROUP BY r.note_id
                ) rem ON rem.note_id = c.note_id
                WHERE n.user_id = %s
                ORDER BY distance LIMIT %s
            )
            SELECT s.chunk_id, s.note_id, s.content, s.chunk_index, s.token_count,
                   s.metadata, s.source_type, s.created_at, s.remind_at, s.distance,
                   ROW_NUMBER() OVER (ORDER BY s.distance) AS rank,
                   (SELECT count(*) FROM note_chunks c2 WHERE c2.note_id = s.note_id)
            FROM scored s ORDER BY s.distance;
            """,
            (query_embedding, user_id, limit),
        )
        rows = cur.fetchall()
    hits, top = [], None
    for row in rows:
        distance = float(row[9])
        similarity = 1.0 - distance
        if top is None:
            top = similarity
        hits.append({
            "rank": row[10], "similarity": round(similarity, 4),
            "distance": round(distance, 4), "rel_to_top": round(top - similarity, 4),
            "content": row[2], "note_id": row[1], "chunk_id": row[0],
            "chunk_index": row[3], "chunk_count": row[11], "source_type": row[6],
            "created_at": row[7], "remind_at": row[8], "token_count": row[4],
            "metadata": row[5],
        })
    return hits
