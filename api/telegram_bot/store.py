"""Persistence for the telegram_bot section (isolated).

All the SQL the bot's endpoints need — notes, chunks, attachments, reminders,
links, users — duplicated here over the shared `db.cursor`. No imports from any
shared domain layer.
"""

from psycopg.types.json import Json

from db import cursor


# ===== notes ===============================================================

def save_note(user_id, text, source_type="text", audio_key=None, audio_mime=None) -> int:
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO notes (user_id, text, source_type, audio_key, audio_mime)
            VALUES (%s, %s, %s, %s, %s) RETURNING id;
            """,
            (user_id, text, source_type, audio_key, audio_mime),
        )
        return cur.fetchone()[0]


def get_text(note_id: int) -> str | None:
    with cursor() as cur:
        cur.execute("SELECT text FROM notes WHERE id = %s;", (note_id,))
        row = cur.fetchone()
        return row[0] if row else None


def set_text(note_id: int, text: str) -> None:
    with cursor() as cur:
        cur.execute("UPDATE notes SET text = %s WHERE id = %s;", (text, note_id))


def get_audio_key(note_id: int) -> str | None:
    with cursor() as cur:
        cur.execute("SELECT audio_key FROM notes WHERE id = %s;", (note_id,))
        row = cur.fetchone()
        return row[0] if row else None


def get_note(note_id: int) -> dict | None:
    with cursor() as cur:
        cur.execute("SELECT text, title, path, tags FROM notes WHERE id = %s;", (note_id,))
        row = cur.fetchone()
        if not row:
            return None
        return {"text": row[0], "title": row[1], "path": row[2], "tags": row[3]}


def get_note_for_user(user_id: int, note_id: int) -> dict | None:
    with cursor() as cur:
        cur.execute("SELECT id FROM notes WHERE id = %s AND user_id = %s;", (note_id, user_id))
        return {"id": note_id} if cur.fetchone() else None


def set_path(note_id: int, path: str) -> None:
    with cursor() as cur:
        cur.execute("UPDATE notes SET path = %s WHERE id = %s;", (path, note_id))


def get_meta(note_id: int) -> dict | None:
    with cursor() as cur:
        cur.execute(
            "SELECT note_type, title, path, tags, priority FROM notes WHERE id = %s;", (note_id,))
        row = cur.fetchone()
        if not row:
            return None
        return {"type": row[0], "title": row[1], "path": row[2],
                "tags": row[3] or [], "priority": row[4]}


def set_metadata(note_id, note_type, title, priority, tags, path) -> None:
    with cursor() as cur:
        cur.execute(
            """
            UPDATE notes SET note_type = %s, title = %s, priority = %s, tags = %s, path = %s
            WHERE id = %s;
            """,
            (note_type, title, priority, Json(tags or []), path, note_id),
        )


def delete_if_bare(note_id: int) -> bool:
    with cursor() as cur:
        cur.execute(
            """
            DELETE FROM notes
            WHERE id = %s AND path IS NULL
              AND NOT EXISTS (SELECT 1 FROM note_links l
                              WHERE l.from_note_id = %s OR l.to_note_id = %s)
              AND NOT EXISTS (SELECT 1 FROM reminders r
                              WHERE r.note_id = %s AND r.status IN ('scheduled', 'postponed'))
            RETURNING id;
            """,
            (note_id, note_id, note_id, note_id),
        )
        return cur.fetchone() is not None


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


def list_tags(user_id: int, limit: int = 30) -> list[tuple[str, int]]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT g, count(*) AS c FROM notes, jsonb_array_elements_text(tags) AS g
            WHERE user_id = %s GROUP BY g ORDER BY c DESC, g LIMIT %s;
            """,
            (user_id, limit),
        )
        return [(r[0], r[1]) for r in cur.fetchall()]


# ===== chunks ==============================================================

def save_chunks(note_id: int, chunks: list[dict]) -> None:
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
                (note_id, ch["index"], ch["content"], ch["token_count"],
                 Json(ch["metadata"]), ch["embedding"]),
            )


def delete_chunks(note_id: int) -> None:
    with cursor() as cur:
        cur.execute("DELETE FROM note_chunks WHERE note_id = %s;", (note_id,))


def similar_notes(user_id, query_embedding, exclude_note_id, limit=5) -> list[dict]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT m.note_type, m.title, m.path, m.tags,
                   MIN(mc.embedding <=> %s::vector) AS distance
            FROM note_chunks mc JOIN notes m ON m.id = mc.note_id
            WHERE m.user_id = %s AND m.id <> %s AND m.title IS NOT NULL
            GROUP BY m.id, m.note_type, m.title, m.path, m.tags
            ORDER BY distance LIMIT %s;
            """,
            (query_embedding, user_id, exclude_note_id, limit),
        )
        return [{"note_type": r[0], "title": r[1], "path": r[2], "tags": r[3],
                 "distance": float(r[4])} for r in cur.fetchall()]


def candidate_notes(user_id, query_embedding, exclude_ids, limit=15) -> list[dict]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT m.id, m.title, m.path, m.tags,
                   MIN(mc.embedding <=> %s::vector) AS distance
            FROM note_chunks mc JOIN notes m ON m.id = mc.note_id
            WHERE m.user_id = %s AND m.title IS NOT NULL AND NOT (m.id = ANY(%s))
            GROUP BY m.id, m.title, m.path, m.tags
            ORDER BY distance LIMIT %s;
            """,
            (query_embedding, user_id, exclude_ids, limit),
        )
        return [{"note_id": r[0], "title": r[1], "path": r[2], "tags": r[3], "distance": r[4]}
                for r in cur.fetchall()]


def search_chunks(user_id, query_embedding, limit=5, remind_start=None, remind_end=None) -> list[dict]:
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


# ===== attachments =========================================================

def add_attachment(note_id, storage_key, kind="image", mime=None, size_bytes=None, position=0) -> int:
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO note_attachments (note_id, kind, storage_key, mime, size_bytes, position)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id;
            """,
            (note_id, kind, storage_key, mime, size_bytes, position),
        )
        return cur.fetchone()[0]


def attachment_keys_for_note(note_id: int) -> list[str]:
    with cursor() as cur:
        cur.execute("SELECT storage_key FROM note_attachments WHERE note_id = %s;", (note_id,))
        return [r[0] for r in cur.fetchall()]


# ===== reminders ===========================================================

def create_reminder(note_id, user_id, remind_at) -> int:
    with cursor() as cur:
        cur.execute(
            "INSERT INTO reminders (note_id, user_id, remind_at) VALUES (%s, %s, %s) RETURNING id;",
            (note_id, user_id, remind_at),
        )
        return cur.fetchone()[0]


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


def count_active(user_id: int) -> int:
    with cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM reminders WHERE user_id = %s AND status IN ('scheduled', 'postponed');",
            (user_id,),
        )
        return cur.fetchone()[0]


def claim_due_reminders(now, stale_before, limit: int = 50):
    with cursor() as cur:
        cur.execute(
            """
            WITH claimed AS (
                UPDATE reminders SET status = 'sending', updated_at = now()
                WHERE id IN (
                    SELECT id FROM reminders
                    WHERE (status IN ('scheduled', 'postponed') AND remind_at <= %s)
                       OR (status = 'sending' AND updated_at < %s)
                    ORDER BY remind_at FOR UPDATE SKIP LOCKED LIMIT %s
                )
                RETURNING id, user_id, note_id, remind_at
            )
            SELECT c.id, c.user_id, u.chat_id, m.text, c.remind_at
            FROM claimed c JOIN notes m ON m.id = c.note_id JOIN users u ON u.id = c.user_id
            ORDER BY c.remind_at;
            """,
            (now, stale_before, limit),
        )
        return cur.fetchall()


def set_reminder_status(reminder_id: int, status: str) -> None:
    with cursor() as cur:
        cur.execute(
            "UPDATE reminders SET status = %s, updated_at = now() WHERE id = %s;",
            (status, reminder_id),
        )


def postpone(reminder_id: int, remind_at) -> None:
    with cursor() as cur:
        cur.execute(
            "UPDATE reminders SET remind_at = %s, status = 'postponed', updated_at = now() WHERE id = %s;",
            (remind_at, reminder_id),
        )


# ===== links ===============================================================

def add_link(from_note_id, to_note_id) -> None:
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO note_links (from_note_id, to_note_id) VALUES (%s, %s)
            ON CONFLICT (from_note_id, to_note_id) DO NOTHING;
            """,
            (from_note_id, to_note_id),
        )


def remove_link(from_note_id, to_note_id) -> None:
    with cursor() as cur:
        cur.execute(
            "DELETE FROM note_links WHERE from_note_id = %s AND to_note_id = %s;",
            (from_note_id, to_note_id),
        )


def is_linked(from_note_id, to_note_id) -> bool:
    with cursor() as cur:
        cur.execute(
            "SELECT 1 FROM note_links WHERE from_note_id = %s AND to_note_id = %s;",
            (from_note_id, to_note_id),
        )
        return cur.fetchone() is not None


# ===== users ===============================================================

def get_or_create_user(chat_id: int, username: str | None = None) -> int:
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (chat_id, username) VALUES (%s, %s)
            ON CONFLICT (chat_id) DO UPDATE
              SET updated_at = now(), username = COALESCE(EXCLUDED.username, users.username)
            RETURNING id;
            """,
            (chat_id, username),
        )
        return cur.fetchone()[0]


def get_settings(user_id: int) -> tuple[str | None, str | None]:
    with cursor() as cur:
        cur.execute("SELECT timezone, language FROM users WHERE id = %s;", (user_id,))
        row = cur.fetchone()
        return (row[0], row[1]) if row else (None, None)


def set_user_timezone(user_id: int, timezone: str) -> None:
    with cursor() as cur:
        cur.execute(
            "UPDATE users SET timezone = %s, updated_at = now() WHERE id = %s;", (timezone, user_id))


def set_user_language(user_id: int, language: str) -> None:
    with cursor() as cur:
        cur.execute(
            "UPDATE users SET language = %s, updated_at = now() WHERE id = %s;", (language, user_id))
