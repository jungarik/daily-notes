"""Contextmenu section service: validate + apply path changes.

Path validation (root-folder in any supported language) is duplicated here over
the shared config + i18n so the section owns its rules.
"""

import logging

import config
import i18n
from api.contextmenu import store

logger = logging.getLogger(__name__)


def _all_root_names() -> set[str]:
    """Every root-folder display name across all supported locales — a path is
    valid if it starts with one, whatever language it was written in."""
    return {i18n.t(loc, key) for key in config.ROOT_FOLDERS for loc in i18n.SUPPORTED}


def clean_root_path(path: str) -> str | None:
    """Normalize a user-entered path and require it to start with a root folder.
    Returns the canonical path, or None if empty / not under a known root."""
    if not path:
        return None
    parts = [p.strip() for p in str(path).replace("\\", "/").split("/")]
    parts = [p for p in parts if p and p not in (".", "..")]
    if not parts:
        return None
    roots = {name.lower(): name for name in _all_root_names()}
    canonical = roots.get(parts[0].lower())
    if canonical is None:
        return None
    return "/".join([canonical] + parts[1:])


def move_note(user_id: int, note_id: int, raw_path: str) -> tuple[str, dict | None]:
    """Owner-scoped: validate + set a single note's full path. Returns
    (status, meta): ('ok', meta) | ('invalid', None) | ('not_found', None)."""
    cleaned = clean_root_path(raw_path)
    if cleaned is None:
        return ("invalid", None)
    if not store.note_exists_for_user(user_id, note_id):
        return ("not_found", None)
    store.set_path(note_id, cleaned)
    logger.info("Note %s (user %s) path set to %r", note_id, user_id, cleaned)
    return ("ok", store.get_meta(note_id))


def move_folder(user_id: int, old_path: str, raw_new_path: str) -> tuple[str, dict | None]:
    """Owner-scoped bulk rename of a sub-folder. Root folders can't be moved.
    Returns (status, data): ('ok', {count, new_path}) | ('invalid', None) | ('root', None)."""
    if "/" not in (old_path or ""):
        return ("root", None)   # a bare root folder — not movable
    cleaned = clean_root_path(raw_new_path)
    if cleaned is None:
        return ("invalid", None)
    count = store.move_folder_paths(user_id, old_path, cleaned)
    logger.info("Moved folder %r -> %r for user %s (%d notes)", old_path, cleaned, user_id, count)
    return ("ok", {"count": count, "new_path": cleaned})
