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

import logging

import config
import i18n
from api import media_token
from common import embedings, helper

logger = logging.getLogger(__name__)

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


def rebuild_chunks(note_id: int, text: str) -> bool:
    """Re-embed the note and swap its chunks. True if they were replaced.

    The note's `note_chunks` are what search, RAG and the link suggestions
    actually match on, so text saved without them is a note that reads
    correctly everywhere and cannot be found by what it now says. Hence this
    runs on every save, not only when the text changed — the editor has no
    reliable "dirty" signal and a redundant re-embed is cheaper than a silent
    mismatch.

    Order is the correctness argument: the chunks are **built first** (the
    OpenAI round trip, the part that fails) and only then swapped inside one
    transaction. Deleting first and failing to insert would leave the note
    invisible to search, which is worse than leaving it matching its old
    wording.

    A failure is logged and swallowed. The note itself is already saved by
    then, and the project's rule is to degrade rather than lose the write —
    reporting an error here would tell the user their text did not save when
    it did.
    """
    try:
        chunks = embedings.build_chunks(text)
    except Exception:
        logger.exception("Embedding failed for note %s; chunks left as they were",
                         note_id)

        return False

    db.replace_chunks(note_id, chunks)
    logger.info("Rebuilt %d chunk(s) for note %s", len(chunks), note_id)

    return True
