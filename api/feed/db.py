"""Persistence for the feed section (isolated).

Only the queries the feed needs, duplicated here so the section owns its data
access. Uses the shared `db.cursor` (core infra); imports nothing from
`stores`.
"""

from db import cursor


def list_notes(user_id: int, limit: int = 2000) -> list[dict]:
    """All of a user's notes, newest first: [{id, title, path, text, tags, type,
    created_at, links}]. `title` may be None (not enriched); the helper supplies a
    fallback. `links` counts links the note participates in (either direction)."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT n.id, n.title, n.path, n.text, n.tags, n.note_type, n.created_at,
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
             "tags": r[4] or [], "type": r[5], "created_at": r[6], "links": r[7]}
            for r in cur.fetchall()
        ]


def all_links(user_id: int, limit: int = 1000) -> list[tuple[int, int]]:
    """Every directed link within the user's vault as [(from_id, to_id)] — both
    endpoints must belong to the user. Feeds the per-note links/backlinks chips."""
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
    """Minimal fields for a set of the user's notes (for link chips):
    [{id, title, text}]."""
    ids = list(ids)
    if not ids:
        return []
    with cursor() as cur:
        cur.execute(
            "SELECT id, title, text FROM notes WHERE user_id = %s AND id = ANY(%s);",
            (user_id, ids),
        )
        return [{"id": r[0], "title": r[1], "text": r[2]} for r in cur.fetchall()]


def attachments_for_notes(note_ids) -> dict[int, list[dict]]:
    """Attachments for many notes at once (avoids N+1): {note_id: [{id, kind,
    mime}, …]} in carousel order. Only notes with attachments appear as keys."""
    ids = list(note_ids)
    if not ids:
        return {}
    out: dict[int, list[dict]] = {}
    with cursor() as cur:
        cur.execute(
            """
            SELECT note_id, id, kind, mime
            FROM note_attachments
            WHERE note_id = ANY(%s)
            ORDER BY note_id, position, id;
            """,
            (ids,),
        )
        for r in cur.fetchall():
            out.setdefault(r[0], []).append({"id": r[1], "kind": r[2], "mime": r[3]})
    return out
