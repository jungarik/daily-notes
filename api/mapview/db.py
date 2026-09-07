"""Persistence for the mapview section (isolated): the vault's edges + the brief
fields of the notes those edges touch."""

from db import cursor


def all_links(user_id: int, limit: int = 1000) -> list[tuple[int, int]]:
    """Every directed link within the user's vault as [(from_id, to_id)]; both
    endpoints must belong to the user."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT l.from_note_id, l.to_note_id
            FROM note_links l
            JOIN notes a ON a.id = l.from_note_id AND a.user_id = %s
            JOIN notes b ON b.id = l.to_note_id AND b.user_id = %s
            LIMIT %s;
            """,
            (user_id, user_id, limit),
        )
        return cur.fetchall()


def notes_brief(user_id: int, ids) -> list[dict]:
    """Node card fields for a set of the user's notes:
    [{id, title, text, path, created_at, attachments}]. The map draws the same
    compact card the chat tab does, so it needs the date and attachment count."""
    ids = list(ids)
    if not ids:
        return []
    with cursor() as cur:
        cur.execute(
            """
            SELECT n.id, n.title, n.text, n.path, n.created_at,
                   (SELECT count(*) FROM note_attachments a
                    WHERE a.note_id = n.id) AS attachments
            FROM notes n
            WHERE n.user_id = %s AND n.id = ANY(%s);
            """,
            (user_id, ids),
        )
        return [{
            "id": r[0],
            "title": r[1],
            "text": r[2],
            "path": r[3],
            "created_at": r[4],
            "attachments": r[5] or 0,
        } for r in cur.fetchall()]
