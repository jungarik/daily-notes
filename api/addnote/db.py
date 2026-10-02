"""Persistence for the addnote section (isolated): the note being edited."""

from db import cursor


def note_for_user(user_id: int, note_id: int) -> dict | None:
    """The note's editable body, owner-scoped, or None.

    The `user_id` predicate is the tenancy guard, not a convenience: without it
    any authenticated caller could read any note by guessing an id. It is in
    the query rather than a check afterwards so there is no path that forgets
    it.

    Only `id` and `text` are selected, because only the textarea is wired. The
    page's path/tags/reminder buttons are disabled, and selecting data for
    controls that cannot use it invites a reader to believe they are live.
    """
    with cursor() as cur:
        cur.execute(
            "SELECT id, text FROM notes WHERE id = %s AND user_id = %s;",
            (note_id, user_id),
        )
        row = cur.fetchone()

        return {"id": row[0], "text": row[1]} if row else None
