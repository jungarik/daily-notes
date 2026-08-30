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


def move_folder_paths(user_id: int, old_path: str, new_path: str) -> int:
    """Bulk-rename: set every one of the user's notes whose path is exactly
    `old_path` to `new_path` (direct notes only). Returns notes moved."""
    with cursor() as cur:
        cur.execute(
            "UPDATE notes SET path = %s WHERE user_id = %s AND path = %s;",
            (new_path, user_id, old_path),
        )
        return cur.rowcount
