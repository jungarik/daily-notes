"""Addnote section service: the signed attachment views and the save rules.

Nothing here touches `db`. `attachment_views` earns its place by being
*impure* in a way a response model cannot be — `media_token.sign` reads the
clock and a secret — and `clean_root_path` / `clean_tags` are pure rules the
endpoint applies to a request. The response itself is assembled in
`endpoints.py`, and so is every database call and the embedding round trip:
this module had a `rebuild_chunks` that called `db.replace_chunks` without
importing `db` at all, which is the shape of mistake that hides in a module
allowed to reach for I/O it has no business doing.

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


# 0–5 topic keywords, the range enrichment produces. A sixth is truncated
# rather than refused: losing the tag the user typed last is friendlier than
# failing a save over it.
TAGS_MAX = 5


def clean_root_path(path: str, locale: str) -> str | None:
    """Normalise a path from the editor, or None if it is not under a root.

    Duplicated from the contextmenu section — a vertical owns its rules, so the
    editor's validation cannot change because the ⋮ menu's did. One difference,
    and it is the behaviour asked for: **an empty path is the default root**,
    not an error. A note saved from this page always lands somewhere.

    A path typed in any supported language is accepted, because
    `_all_root_names` spans the locales; `locale` only decides what an empty
    path becomes.
    """
    if not (path or "").strip():
        return default_root(locale)

    parts = [part.strip() for part in str(path).replace("\\", "/").split("/")]
    parts = [part for part in parts if part and part not in (".", "..")]

    if not parts:
        return default_root(locale)

    roots = {name.lower(): name
             for name in {i18n.t(loc, key)
                          for key in config.ROOT_FOLDERS
                          for loc in i18n.SUPPORTED}}
    canonical = roots.get(parts[0].lower())

    if canonical is None:
        return None

    return "/".join([canonical] + parts[1:])


def clean_tags(tags: list[str] | None) -> list[str]:
    """Trim, drop blanks, de-duplicate case-insensitively, cap at `TAGS_MAX`.

    Pure, and order-preserving: the user's own order is the only one that means
    anything, and sorting would shuffle a list they just typed. The duplicate
    check is case-insensitive but the *kept* spelling is the first one, so
    "Work" survives and a later "work" does not become a second tag that
    renders identically.
    """
    seen, out = set(), []

    for tag in tags or []:
        label = str(tag).strip()
        key = label.lower()

        if not label or key in seen:
            continue

        seen.add(key)
        out.append(label)

    return out[:TAGS_MAX]
