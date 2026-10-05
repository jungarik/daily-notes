"""Persistence for the explorer section (isolated): notes, and the language
their folder roster is labelled in.

The language lookup is duplicated from the other verticals rather than
shared: a section owns the SQL it needs (see CLAUDE.md).
"""

from db import cursor


def list_notes(user_id: int, limit: int = 2000) -> list[dict]:
    """All of a user's notes for the tree, newest first: [{id, title, path, text,
    created_at, links}]. `title` may be None (not enriched); the helper supplies a
    fallback and a text snippet. `links` counts links the note participates in."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT n.id, n.path, n.text, n.created_at,
                   (SELECT count(*) FROM note_links l
                    WHERE l.from_note_id = n.id OR l.to_note_id = n.id) AS links
            FROM notes n
            -- An un-filed note (no path) is not part of the vault yet: it is
            -- hidden from every browsing view until enrichment gives it a
            -- home. The bot and the chat agents still see it, so it stays
            -- recoverable. Duplicated per section, like the rest of the SQL.
            WHERE n.user_id = %s AND n.path IS NOT NULL AND n.path <> ''
            ORDER BY n.created_at DESC NULLS LAST, n.id DESC
            LIMIT %s;
            """,
            (user_id, limit),
        )
        return [
            {"id": r[0], "path": r[1], "text": r[2],
             "created_at": r[3], "links": r[4]}
            for r in cur.fetchall()
        ]


def get_language(user_id: int) -> str | None:
    """The user's chosen language, or None when they have never set one.

    Only the bot writes this column, so a Mini-App-only user has NULL here and
    the caller decides what that means.
    """
    with cursor() as cur:
        cur.execute("SELECT language FROM users WHERE id = %s;", (user_id,))
        row = cur.fetchone()

    return row[0] if row else None
