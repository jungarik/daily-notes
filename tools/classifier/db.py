"""Database adapter used only by classifier tool handlers.

Duplicated from `tools/enricher/db.py` rather than shared, for the reason
CLAUDE.md gives: a vertical owns the persistence it needs so one agent's SQL
cannot ripple into another's. Only the queries filing a note actually needs are
here — the vault vocabulary it files against, the note it reads, the metadata
it writes, and one hop of turn state.
"""

from psycopg.types.json import Json

from db import cursor


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
            SELECT g, count(*) AS c
            FROM notes, jsonb_array_elements_text(tags) AS g
            WHERE user_id = %s GROUP BY g ORDER BY c DESC, g LIMIT %s;
            """,
            (user_id, limit),
        )
        return [(r[0], r[1]) for r in cur.fetchall()]


def similar_notes(user_id: int, query_embedding: str, exclude_note_id: int,
                  limit: int = 5) -> list[dict]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT m.id, m.note_type, m.title, m.path, m.tags,
                   MIN(mc.embedding <=> %s::vector) AS distance
            FROM note_chunks mc JOIN notes m ON m.id = mc.note_id
            WHERE m.user_id = %s AND m.id <> %s AND m.title IS NOT NULL
            GROUP BY m.id, m.note_type, m.title, m.path, m.tags
            ORDER BY distance LIMIT %s;
            """,
            (query_embedding, user_id, exclude_note_id, limit),
        )
        return [{"note_id": r[0], "note_type": r[1], "title": r[2],
                 "path": r[3], "tags": r[4], "distance": float(r[5])}
                for r in cur.fetchall()]


def related_notes(user_id: int, query_embedding: str, limit: int = 5) -> list[dict]:
    """User-owned notes nearest a text, when there is no note to exclude."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT n.id, n.note_type, n.title, n.path, n.tags,
                   MIN(c.embedding <=> %s::vector) AS distance
            FROM note_chunks c JOIN notes n ON n.id = c.note_id
            WHERE n.user_id = %s AND n.title IS NOT NULL
            GROUP BY n.id, n.note_type, n.title, n.path, n.tags
            ORDER BY distance LIMIT %s;
            """,
            (query_embedding, user_id, limit),
        )
        return [{"note_id": r[0], "note_type": r[1], "title": r[2],
                 "path": r[3], "tags": r[4] or [], "distance": float(r[5])}
                for r in cur.fetchall()]


def get_note_for_user(user_id: int, note_id: int) -> dict | None:
    with cursor() as cur:
        cur.execute(
            """
            SELECT id, text, title, path, tags, note_type, priority
            FROM notes WHERE id = %s AND user_id = %s;
            """,
            (note_id, user_id),
        )
        row = cur.fetchone()

        if not row:
            return None

        return {"id": row[0], "text": row[1], "title": row[2], "path": row[3],
                "tags": row[4] or [], "type": row[5], "priority": row[6]}


def set_metadata(note_id, note_type, title, priority, tags, path) -> None:
    with cursor() as cur:
        cur.execute(
            """
            UPDATE notes SET note_type = %s, title = %s, priority = %s, tags = %s, path = %s
            WHERE id = %s;
            """,
            (note_type, title, priority, Json(tags or []), path, note_id),
        )


def get_state(state_id: str, user_id: int) -> dict | None:
    """One saved hop of this turn, scoped to its owner.

    The owner check is not the allowlist — it is the same tenancy guard every
    other tool applies, so a state id from one user's turn can never read
    another's row however the allowlist is configured.
    """
    with cursor() as cur:
        cur.execute(
            """
            SELECT agent, status, state
            FROM agent_states
            WHERE state_id = %s AND user_id = %s;
            """,
            (state_id, user_id),
        )
        row = cur.fetchone()

    if row is None:
        return None

    return {"agent": row[0], "status": row[1], "state": row[2]}
