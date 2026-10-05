"""Feed section service: shape note rows into full feed cards.

Duplicated shaping (display title, link chips, attachment views + signed URLs)
so the section is self-contained. Depends only on its own store and the shared
media_token (core infra).
"""

from api import media_token

# The image proxy lives in the notecard section; an <img> can't send the auth
# header, so the signed token in the URL is the auth. Path is relative (same
# origin as the API from the browser's perspective).
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


def attachment_views(rows: list[dict]) -> list[dict]:
    """Client-facing attachments with a signed proxy URL: [{id, kind, mime, url}]."""
    out = []
    for a in rows:
        out.append({
            "id": a["id"], "kind": a["kind"], "mime": a["mime"],
            "url": _ATTACHMENT_URL.format(id=a["id"], token=media_token.sign(a["id"])),
        })
    return out


def feed_for_user(
    notes: list[dict],
    edges: list[tuple[int, int]],
    briefs: list[dict],
    attachments: dict[int, list[dict]],
) -> list[dict]:
    """Map bulk-loaded note data to full feed cards (newest first)."""
    briefs_by_id = {brief["id"]: brief for brief in briefs}
    out_map: dict[int, list[int]] = {}
    in_map: dict[int, list[int]] = {}
    for f, t in edges:
        out_map.setdefault(f, []).append(t)
        in_map.setdefault(t, []).append(f)

    def chip(nid: int) -> dict:
        b = briefs_by_id.get(nid)
        return {"id": nid, "label": _note_label(b["text"]) if b else str(nid)}

    feed = []
    for n in notes:
        created = n.get("created_at")
        feed.append({
            "id": n["id"],
            "label": _note_label(n["text"]),
            "path": n["path"],
            "text": n["text"] or "",
            "tags": n.get("tags") or [],
            "type": n.get("type"),
            "created_at": created.isoformat() if created else None,
            "links": [chip(t) for t in out_map.get(n["id"], [])],
            "backlinks": [chip(f) for f in in_map.get(n["id"], [])],
            "attachments": attachments.get(n["id"], []),
        })
    return feed
