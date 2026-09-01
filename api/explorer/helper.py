"""Explorer section service: shape note rows for the tree/list."""

from api.explorer import db


def _display_title(title: str | None, text: str | None, limit: int = 60) -> str:
    t = (title or "").strip()
    if t:
        return t
    snippet = " ".join((text or "").split())
    if not snippet:
        return "untitled"
    return snippet[:limit] + "…" if len(snippet) > limit else snippet


def list_for_tree(user_id: int) -> list[dict]:
    """The user's notes for the explorer tree (newest first): [{id, title, path,
    snippet, created_at, links}]."""
    out = []
    for n in db.list_notes(user_id):
        created = n.get("created_at")
        out.append({
            "id": n["id"],
            "title": _display_title(n["title"], n["text"]),
            "path": n["path"],
            "snippet": " ".join((n["text"] or "").split())[:160],
            "created_at": created.isoformat() if created else None,
            "links": n["links"],
        })
    return out
