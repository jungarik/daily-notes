"""Addnote section service: the signed attachment views.

One function, and it earns its place by being *impure*: `media_token.sign`
reads the clock and a secret, so it cannot live in a response model. The rest
of the response is assembled in `endpoints.py` — the row's three nullable
columns are coerced there, inline, rather than through a mapper that would add
a name to read past for `value or ""`.

The URL template and the signing call are duplicated from the feed section
rather than shared. That is the deliberate trade in this codebase — a vertical
owns its shaping so one section's change cannot ripple into another's — and
`media_token` itself is the shared infra both reach for.
"""

import config
import i18n
from api import media_token
from common import helper

# The proxy lives in the notecard section: an <img> cannot send the initData
# header, so the signed token in the URL is the auth. Relative, so it resolves
# against whatever origin served the API to this browser.
_ATTACHMENT_URL = "/api/notecard/attachments/{id}?t={token}"


def attachment_views(rows: list[dict]) -> list[dict]:
    """Client-facing attachments with a signed proxy URL: [{id, kind, mime, url}].

    Row order is kept — it is the carousel's `position, id` from the query, so
    re-sorting here would silently disagree with the feed and the card.
    """
    return [
        {
            "id": row["id"],
            "kind": row["kind"],
            "mime": row["mime"],
            "url": _ATTACHMENT_URL.format(id=row["id"],
                                          token=media_token.sign(row["id"])),
        }
        for row in rows
    ]


def root_labels(locale: str) -> list[str]:
    """The vault's root folders in canonical order, in one language.

    `common.helper.order_root_keys()` is the single source of that order, so
    this does not restate it. One locale, because this list is shown to a user:
    four translations of Inbox in a wheel is noise.
    """
    return [i18n.t(locale, key) for key in helper.order_root_keys()]


def default_root(locale: str) -> str:
    """Where a note goes when nobody picks: `config.DEFAULT_ROOT_FOLDER_KEY`.

    The key, localised here rather than guessed from the roster's first entry —
    the order and the default are two different decisions and the day they
    disagree, reading position 0 would silently file notes somewhere else.
    """
    return i18n.t(locale, config.DEFAULT_ROOT_FOLDER_KEY)


def known_paths(roots: list[str], note_paths: list[str]) -> list[str]:
    """Every path the picker offers: the roots plus whatever is in use.

    A strict pure mapper — the endpoint reads the language and the rows. Roots
    are included even when empty, because an empty root is exactly where a note
    gets filed. A path under an unrecognised root — one left behind by a
    language switch — sorts last rather than being dropped, which would hide
    the only route back to those notes.

    Duplicated from the contextmenu section, deliberately: same reason as the
    SQL above.
    """
    rank = {label: index for index, label in enumerate(roots)}
    seen = list(dict.fromkeys(path for path in list(roots) + list(note_paths)
                              if path and path.strip()))

    def sort_key(path: str) -> tuple:
        root = path.split("/")[0]

        return (rank.get(root, len(rank)), path if root in rank else root, path)

    return sorted(seen, key=sort_key)
