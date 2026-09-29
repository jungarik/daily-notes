"""Explorer section service: the tree's note rows, and the root roster that
gives its top level an order.
"""

import i18n
from api.explorer import db
from common import helper


def _display_title(title: str | None, text: str | None, limit: int = 60) -> str:
    t = (title or "").strip()
    if t:
        return t
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
            "title": _display_title(n["title"], n["text"]),
            "path": n["path"],
            "snippet": " ".join((n["text"] or "").split())[:160],
            "created_at": created.isoformat() if created else None,
            "links": n["links"],
        })
    return out
