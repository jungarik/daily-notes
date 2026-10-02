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

from api import media_token

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
