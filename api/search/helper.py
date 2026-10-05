"""Search section service: shape matched notes into result rows."""

from api.search import db


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


def search(user_id: int, query: str) -> list[dict]:
    """Result rows for a query: [{id, title, path, snippet}]. Empty query → []."""
    q = (query or "").strip()
    if not q:
        return []
    out = []
    for n in db.search_notes(user_id, q):
        out.append({
            "id": n["id"],
            "label": _note_label(n["text"]),
            "path": n["path"],
            "snippet": " ".join((n["text"] or "").split())[:160],
        })
    return out
