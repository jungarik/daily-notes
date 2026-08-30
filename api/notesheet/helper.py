"""Notesheet section service: shape one note into a full detail card."""

from api import media_token
from api.notesheet import store

_ATTACHMENT_URL = "/api/notecard/attachments/{id}?t={token}"


def _display_title(title: str | None, text: str | None, limit: int = 60) -> str:
    t = (title or "").strip()
    if t:
        return t
    snippet = " ".join((text or "").split())
    if not snippet:
        return "untitled"
    return snippet[:limit] + "…" if len(snippet) > limit else snippet


def _attachment_views(rows: list[dict]) -> list[dict]:
    return [{
        "id": a["id"], "kind": a["kind"], "mime": a["mime"],
        "url": _ATTACHMENT_URL.format(id=a["id"], token=media_token.sign(a["id"])),
    } for a in rows]


def note_detail(user_id: int, note_id: int) -> dict | None:
    """Full note detail for the preview, scoped to its owner. None if not found."""
    n = store.get_note_for_user(user_id, note_id)
    if n is None:
        return None
    created = n.get("created_at")

    links, backlinks = [], []
    for _id, title, text, direction in store.neighbours(user_id, note_id):
        (links if direction == "out" else backlinks).append(
            {"id": _id, "title": _display_title(title, text)}
        )

    return {
        "id": n["id"],
        "title": _display_title(n["title"], n["text"]),
        "path": n["path"],
        "text": n["text"] or "",
        "tags": n["tags"] or [],
        "type": n["type"],
        "created_at": created.isoformat() if created else None,
        "links": links,
        "backlinks": backlinks,
        "attachments": _attachment_views(store.list_attachments(note_id)),
    }
