"""Notesheet section service: shape one note into a full detail card."""

from api import media_token
from api.notesheet import db

_ATTACHMENT_URL = "/api/notecard/attachments/{id}?t={token}"


# Every surface that lists notes cuts the label at the same length, so the
# feed's link chips, the explorer's rows, a search hit and the sheet's linked
# notes all read alike. Each still clips to its own width in CSS on top of it.
LABEL_CHARS = 60


def _note_label(text: str | None, limit: int = LABEL_CHARS) -> str:
    """A note's label: the first `limit` characters of its own text.

    The enriched `title` is deliberately **not** consulted. It is an LLM's
    one-line summary, so a list of titles is a list of the model's words where
    the user is looking for their own; the note's opening is what they
    recognise. `notes.title` still exists and enrichment still writes it — it
    is simply not what the web app shows.

    Whitespace is collapsed first: a note that starts with a newline would
    otherwise render as a blank row.
    """
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
    n = db.get_note_for_user(user_id, note_id)
    if n is None:
        return None
    created = n.get("created_at")

    links, backlinks = [], []
    for _id, text, direction in db.neighbours(user_id, note_id):
        (links if direction == "out" else backlinks).append(
            {"id": _id, "label": _note_label(text)}
        )

    return {
        "id": n["id"],
        "label": _note_label(n["text"]),
        "path": n["path"],
        "text": n["text"] or "",
        "tags": n["tags"] or [],
        "type": n["type"],
        "created_at": created.isoformat() if created else None,
        "links": links,
        "backlinks": backlinks,
        "attachments": _attachment_views(db.list_attachments(note_id)),
    }
