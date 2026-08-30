"""Persistence for the browser section (isolated): the user's notes list."""

from db import cursor


def list_notes(user_id: int, limit: int = 2000) -> list[dict]:
    """All of a user's notes for the tree, newest first: [{id, title, path, text,
    created_at, links}]. `title` may be None (not enriched); the helper supplies a
    fallback and a text snippet. `links` counts links the note participates in."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT n.id, n.title, n.path, n.text, n.created_at,
                   (SELECT count(*) FROM note_links l
                    WHERE l.from_note_id = n.id OR l.to_note_id = n.id) AS links
            FROM notes n
            WHERE n.user_id = %s
            ORDER BY n.created_at DESC NULLS LAST, n.id DESC
            LIMIT %s;
            """,
            (user_id, limit),
        )
        return [
            {"id": r[0], "title": r[1], "path": r[2], "text": r[3],
             "created_at": r[4], "links": r[5]}
            for r in cur.fetchall()
        ]
