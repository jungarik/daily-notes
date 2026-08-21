"""Persistence for note attachments (media files).

The bytes live in object storage (see `storage`); these rows keep only the
object key plus metadata (kind/mime/size) and the carousel `position`. One note
has many attachments.
"""

from db import cursor


def add_attachment(
    note_id: int,
    storage_key: str,
    kind: str = "image",
    mime: str | None = None,
    size_bytes: int | None = None,
    position: int = 0,
) -> int:
    """Insert one attachment row and return its id."""
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO note_attachments
                (note_id, kind, storage_key, mime, size_bytes, position)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (note_id, kind, storage_key, mime, size_bytes, position),
        )
        return cur.fetchone()[0]


def _row(r) -> dict:
    return {"id": r[0], "note_id": r[1], "kind": r[2],
            "storage_key": r[3], "mime": r[4], "position": r[5]}


def get(attachment_id: int) -> dict | None:
    """One attachment by id (for the media proxy): {id, note_id, kind,
    storage_key, mime, position}, or None."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT id, note_id, kind, storage_key, mime, position
            FROM note_attachments WHERE id = %s;
            """,
            (attachment_id,),
        )
        row = cur.fetchone()
        return _row(row) if row else None


def list_for_note(note_id: int) -> list[dict]:
    """A note's attachments in carousel order: [{id, note_id, kind, storage_key,
    mime, position}]."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT id, note_id, kind, storage_key, mime, position
            FROM note_attachments
            WHERE note_id = %s
            ORDER BY position, id;
            """,
            (note_id,),
        )
        return [_row(r) for r in cur.fetchall()]


def for_notes(note_ids) -> dict[int, list[dict]]:
    """Attachments for many notes at once (avoids N+1 in the feed): returns
    {note_id: [attachment, …]} with each list in carousel order. Only notes that
    have attachments appear as keys."""
    ids = list(note_ids)
    if not ids:
        return {}
    out: dict[int, list[dict]] = {}
    with cursor() as cur:
        cur.execute(
            """
            SELECT id, note_id, kind, storage_key, mime, position
            FROM note_attachments
            WHERE note_id = ANY(%s)
            ORDER BY note_id, position, id;
            """,
            (ids,),
        )
        for r in cur.fetchall():
            out.setdefault(r[1], []).append(_row(r))
    return out
