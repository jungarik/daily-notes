"""Viewnote section service: the signed attachment views and the root labels.

Nothing here touches `db`. `attachment_views` earns its place by being
*impure* in a way a response model cannot be — `media_token.sign` reads the
clock and a secret — and the two label functions are pure over the locale they
are given. The response itself is assembled in `endpoints.py`, which is also
where every database call lives: a helper allowed to reach for I/O it has no
business doing is a helper that can forget to import it.

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
