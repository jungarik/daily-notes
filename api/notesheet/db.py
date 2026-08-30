"""Persistence for the notesheet section (isolated): one note + its neighbours
+ its attachments, all owner-scoped."""

from db import cursor


def get_note_for_user(user_id: int, note_id: int) -> dict | None:
    """Full note detail scoped to its owner, or None if it isn't the user's."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT id, text, title, path, tags, note_type, created_at
            FROM notes WHERE id = %s AND user_id = %s;
            """,
            (note_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0], "text": row[1], "title": row[2], "path": row[3],
            "tags": row[4] or [], "type": row[5], "created_at": row[6],
        }


def neighbours(user_id: int, note_id: int, limit: int = 100):
    """Direct neighbours (depth 1 only), owner-scoped: [(id, title, text,
    direction)] where direction is 'out' (a link) or 'in' (a backlink). A single
    non-recursive query, so link cycles are harmless."""
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
            ORDER BY direction
            LIMIT %s;
            """,
            (note_id, user_id, note_id, user_id, limit),
        )
        return cur.fetchall()


def list_attachments(note_id: int) -> list[dict]:
    """A note's attachments in carousel order: [{id, kind, mime}]."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT id, kind, mime FROM note_attachments
            WHERE note_id = %s ORDER BY position, id;
            """,
            (note_id,),
        )
        return [{"id": r[0], "kind": r[1], "mime": r[2]} for r in cur.fetchall()]
