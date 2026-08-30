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
    """Minimal node fields for a set of the user's notes: [{id, title, text, path}]."""
    ids = list(ids)
    if not ids:
        return []
    with cursor() as cur:
        cur.execute(
            "SELECT id, title, text, path FROM notes WHERE user_id = %s AND id = ANY(%s);",
            (user_id, ids),
        )
        return [{"id": r[0], "title": r[1], "text": r[2], "path": r[3]} for r in cur.fetchall()]
