"""Explorer section service: the tree's note rows, and the root roster that
gives its top level an order.
"""

import i18n
from api.explorer import db
from common import helper


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


def list_roots(user_id: int) -> list[dict]:
    """Every root folder, labelled in the user's language, in canonical order.

    All of them — including Archive — because this is the vault's roster, not a
    selection for one screen.
    """
    locale = i18n.resolve_locale(db.get_language(user_id))

    return [{"key": key, "label": i18n.t(locale, key)}
            for key in helper.order_root_keys()]


def list_for_tree(user_id: int) -> list[dict]:
    """The user's notes for the explorer tree (newest first): [{id, title, path,
    snippet, created_at, links}]."""
    out = []
    for n in db.list_notes(user_id):
        created = n.get("created_at")
        out.append({
            "id": n["id"],
            "label": _note_label(n["text"]),
            "path": n["path"],
            "snippet": " ".join((n["text"] or "").split())[:160],
            "created_at": created.isoformat() if created else None,
            "links": n["links"],
        })
    return out
