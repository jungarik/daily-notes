"""Persistence for the chat agent (isolated SQL) — reads + thread state only.

The chat agent is read-only, so this holds only the queries its read tools and
RAG need, plus chat-thread persistence. All writes live in the enrich agent.
"""

from psycopg.types.json import Json

from db import cursor


# ----- note reads -----

def notes_brief(user_id: int, ids) -> list[dict]:
    ids = list(ids)
    if not ids:
        return []
    with cursor() as cur:
        cur.execute(
            "SELECT id, title, text, path FROM notes WHERE user_id = %s AND id = ANY(%s);",
            (user_id, ids),
        )
        return [{"id": r[0], "title": r[1], "text": r[2], "path": r[3]} for r in cur.fetchall()]


def get_note_for_user(user_id: int, note_id: int) -> dict | None:
    with cursor() as cur:
        cur.execute(
            "SELECT id, text, title, path, tags FROM notes WHERE id = %s AND user_id = %s;",
            (note_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "text": row[1], "title": row[2], "path": row[3], "tags": row[4] or []}


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
        return [(r[0], r[1]) for r in cur.fetchall()]


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
            SELECT r.id, r.remind_at, m.text, r.status
            FROM reminders r JOIN notes m ON m.id = r.note_id
            WHERE r.user_id = %s AND r.status IN ('scheduled', 'postponed')
            ORDER BY r.remind_at LIMIT %s;
            """,
            (user_id, limit),
        )
        return cur.fetchall()


def get_user_settings(user_id: int) -> tuple[str | None, str | None]:
    with cursor() as cur:
        cur.execute("SELECT timezone, language FROM users WHERE id = %s;", (user_id,))
        row = cur.fetchone()
        return (row[0], row[1]) if row else (None, None)


# ----- RAG retrieval -----

def search_chunks(user_id: int, query_embedding: str, limit: int = 5,
                  remind_start=None, remind_end=None) -> list[dict]:
    filtering = remind_start is not None and remind_end is not None
    remind_range = "AND r.remind_at >= %s AND r.remind_at < %s" if filtering else ""
    where_filter = "AND rem.remind_at IS NOT NULL" if filtering else ""
    params: list = [query_embedding]
    if filtering:
        params += [remind_start, remind_end]
    params += [user_id, limit]
    with cursor() as cur:
        cur.execute(
            f"""
            WITH scored AS (
                SELECT mc.id AS chunk_id, mc.note_id AS note_id, mc.content AS content,
                       mc.chunk_index AS chunk_index, mc.token_count AS token_count,
                       mc.metadata AS metadata, m.source_type AS source_type,
                       m.created_at AS created_at, rem.remind_at AS remind_at,
                       (mc.embedding <=> %s::vector) AS distance
                FROM note_chunks mc JOIN notes m ON m.id = mc.note_id
                LEFT JOIN (
                    SELECT r.note_id, MIN(r.remind_at) AS remind_at FROM reminders r
                    WHERE r.status IN ('scheduled', 'postponed') {remind_range}
                    GROUP BY r.note_id
                ) rem ON rem.note_id = mc.note_id
                WHERE m.user_id = %s {where_filter}
                ORDER BY distance LIMIT %s
            )
            SELECT s.chunk_id, s.note_id, s.content, s.chunk_index, s.token_count,
                   s.metadata, s.source_type, s.created_at, s.remind_at, s.distance,
                   ROW_NUMBER() OVER (ORDER BY s.distance) AS rank,
                   (SELECT count(*) FROM note_chunks c2 WHERE c2.note_id = s.note_id) AS chunk_count
            FROM scored s ORDER BY s.distance;
            """,
            tuple(params),
        )
        rows = cur.fetchall()
    hits, top = [], None
    for r in rows:
        distance = float(r[9]); similarity = 1.0 - distance
        if top is None:
            top = similarity
        hits.append({
            "rank": r[10], "similarity": round(similarity, 4), "distance": round(distance, 4),
            "rel_to_top": round(top - similarity, 4), "content": r[2], "note_id": r[1],
            "chunk_id": r[0], "chunk_index": r[3], "chunk_count": r[11],
            "source_type": r[6], "created_at": r[7], "remind_at": r[8],
            "token_count": r[4], "metadata": r[5],
        })
    return hits


# ----- chat threads -----

def create_thread(user_id: int) -> int:
    with cursor() as cur:
        cur.execute("INSERT INTO chat_threads (user_id) VALUES (%s) RETURNING id;", (user_id,))
        return cur.fetchone()[0]


def get_thread(user_id: int, thread_id: int) -> dict | None:
    with cursor() as cur:
        cur.execute(
            "SELECT id, messages, pending FROM chat_threads WHERE id = %s AND user_id = %s;",
            (thread_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "messages": row[1] or [], "pending": row[2]}


def save_thread(thread_id: int, messages: list, pending: dict | None) -> None:
    with cursor() as cur:
        cur.execute(
            "UPDATE chat_threads SET messages = %s, pending = %s, updated_at = now() WHERE id = %s;",
            (Json(messages), Json(pending) if pending is not None else None, thread_id),
        )
