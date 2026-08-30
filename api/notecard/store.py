"""Persistence for the notecard section (isolated): one attachment's row."""

from db import cursor


def get_attachment(attachment_id: int) -> dict | None:
    """The attachment's storage key + mime for the proxy: {id, storage_key,
    mime}, or None. Deliberately not user-scoped — the signed token is the auth."""
    with cursor() as cur:
        cur.execute(
            "SELECT id, storage_key, mime FROM note_attachments WHERE id = %s;",
            (attachment_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "storage_key": row[1], "mime": row[2]}
