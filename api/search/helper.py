"""Search section service: shape matched notes into result rows."""

from api.search import store


def _display_title(title: str | None, text: str | None, limit: int = 60) -> str:
    t = (title or "").strip()
    if t:
        return t
    snippet = " ".join((text or "").split())
    if not snippet:
        return "untitled"
    return snippet[:limit] + "…" if len(snippet) > limit else snippet


def search(user_id: int, query: str) -> list[dict]:
    """Result rows for a query: [{id, title, path, snippet}]. Empty query → []."""
    q = (query or "").strip()
    if not q:
        return []
    out = []
    for n in store.search_notes(user_id, q):
        out.append({
            "id": n["id"],
            "title": _display_title(n["title"], n["text"]),
            "path": n["path"],
            "snippet": " ".join((n["text"] or "").split())[:160],
        })
    return out
