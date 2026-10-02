"""Persistence for the addnote section (isolated): the note being edited."""

from db import cursor


def note_for_user(user_id: int, note_id: int) -> dict | None:
    """The note's editable body, owner-scoped, or None.

    The `user_id` predicate is the tenancy guard, not a convenience: without it
    any authenticated caller could read any note by guessing an id. It is in
    the query rather than a check afterwards so there is no path that forgets
    it.

    `path` and `tags` ride along with the body because they belong to the same
    row — a second query for two columns of the row already in hand would be a
    query for nothing.
    """
    with cursor() as cur:
        cur.execute(
            "SELECT id, text, path, tags FROM notes WHERE id = %s AND user_id = %s;",
            (note_id, user_id),
        )
        row = cur.fetchone()

        return ({"id": row[0], "text": row[1], "path": row[2], "tags": row[3]}
                if row else None)


def attachments(note_id: int) -> list[dict]:
    """The note's attachments in carousel order: [{id, kind, mime}].

    No owner predicate and none needed: the caller has already established
    ownership of the note, and `note_id` is not user input by the time it gets
    here. `position, id` is the same order the feed and the card use, so the
    editor's first photo is the one the user saw first.

    The storage key is not selected. Nothing client-facing may carry it — the
    bucket is private and the signed proxy URL is the only way in.
    """
    with cursor() as cur:
        cur.execute(
            """
            SELECT id, kind, mime FROM note_attachments
            WHERE note_id = %s ORDER BY position, id;
            """,
            (note_id,),
        )
        return [{"id": r[0], "kind": r[1], "mime": r[2]} for r in cur.fetchall()]


def linked_note_ids(user_id: int, note_id: int) -> list[int]:
    """Every note this one is connected to, in either direction.

    Links are directed and backlinks are the reverse query, so a note's
    neighbours are the union of both — the same set the card's chips show. The
    `user_id` predicate is on the *other* endpoint: a link whose far side
    belongs to someone else must not leak that note's id, and the rows are
    reachable because this note's owner wrote the edge.

    Returned as a sorted list rather than a set so the response is stable: an
    unordered payload makes a diff between two reads unreadable.
    """
    with cursor() as cur:
        cur.execute(
            """
            SELECT l.to_note_id FROM note_links l
            JOIN notes n ON n.id = l.to_note_id AND n.user_id = %s
            WHERE l.from_note_id = %s
            UNION
            SELECT l.from_note_id FROM note_links l
            JOIN notes n ON n.id = l.from_note_id AND n.user_id = %s
            WHERE l.to_note_id = %s;
            """,
            (user_id, note_id, user_id, note_id),
        )
        return sorted(row[0] for row in cur.fetchall())
