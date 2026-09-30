"""Persistence for the contextmenu section (isolated): path reads/writes."""

from db import cursor


def note_exists_for_user(user_id: int, note_id: int) -> bool:
    """True if the note is the user's (ownership guard before a path change)."""
    with cursor() as cur:
        cur.execute(
            "SELECT 1 FROM notes WHERE id = %s AND user_id = %s;", (note_id, user_id)
        )
        return cur.fetchone() is not None


def set_path(note_id: int, path: str) -> None:
    """Update just a note's vault path (leaves other metadata untouched)."""
    with cursor() as cur:
        cur.execute("UPDATE notes SET path = %s WHERE id = %s;", (path, note_id))


def get_meta(note_id: int) -> dict | None:
    """The note's enrichment metadata {type, title, path, tags, priority}, or None."""
    with cursor() as cur:
        cur.execute(
            "SELECT note_type, title, path, tags, priority FROM notes WHERE id = %s;",
            (note_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"type": row[0], "title": row[1], "path": row[2],
                "tags": row[3] or [], "priority": row[4]}


def object_keys(note_id: int) -> list[str]:
    """Every bucket object this note owns — attachments plus its voice audio.

    Read this BEFORE deleting the note. `note_attachments.note_id` cascades, so
    afterwards the rows naming these keys are gone and the objects are orphaned
    with nothing left to identify them.

    Both kinds arrive as one list because the bucket does not distinguish them:
    the caller is about to hand each to `file_store.delete_object`.
    """
    with cursor() as cur:
        cur.execute(
            """
            SELECT storage_key FROM note_attachments WHERE note_id = %s
            UNION ALL
            SELECT audio_key FROM notes WHERE id = %s AND audio_key IS NOT NULL;
            """,
            (note_id, note_id),
        )
        return [row[0] for row in cur.fetchall()]


def delete_note(user_id: int, note_id: int) -> bool:
    """Hard-delete the note, owner-scoped. True if a row went.

    The `user_id` predicate is the tenancy guard, not a convenience: without it
    any authenticated caller could delete any note by guessing an id.

    Dependants go with it by cascade — `note_chunks`, `note_attachments`,
    `note_links` (both directions) and `reminders`. Unlike the bot's
    `delete_if_bare` this has no conditions: a filed note, a linked note and a
    note with a reminder still to come all delete, which is what makes it the
    web app's Delete rather than its cleanup.
    """
    with cursor() as cur:
        cur.execute(
            "DELETE FROM notes WHERE id = %s AND user_id = %s RETURNING id;",
            (note_id, user_id),
        )
        return cur.fetchone() is not None


def move_folder_paths(user_id: int, old_path: str, new_path: str) -> int:
    """Bulk-rename: set every one of the user's notes whose path is exactly
    `old_path` to `new_path` (direct notes only). Returns notes moved."""
    with cursor() as cur:
        cur.execute(
            "UPDATE notes SET path = %s WHERE user_id = %s AND path = %s;",
            (new_path, user_id, old_path),
        )
        return cur.rowcount
