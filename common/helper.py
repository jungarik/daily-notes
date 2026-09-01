"""Shared deterministic note metadata helpers."""

import config
import i18n

TYPES = ("idea", "task", "reminder", "note", "question", "link")
PRIORITIES = ("low", "med", "high")


def localized_root_folders(language: str | None) -> tuple[dict[str, str], str]:
    locale = i18n.normalize(language) or i18n.DEFAULT_LOCALE
    roots = {i18n.t(locale, key): definition
             for key, definition in config.ROOT_FOLDERS.items()}
    default = i18n.t(locale, config.DEFAULT_ROOT_FOLDER_KEY)
    return roots, default


def clean_path(raw) -> str | None:
    if not raw:
        return None
    parts = [p.strip() for p in str(raw).replace("\\", "/").split("/")]
    parts = [p for p in parts if p and p not in (".", "..")][:2]
    return "/".join(parts) or None


def enforce_root(path, root_folders, default_root_folder):
    if not path:
        return default_root_folder

    if not root_folders:
        return path

    roots = {name.lower(): name for name in root_folders}
    parts = path.split("/")
    canonical = roots.get(parts[0].lower())

    if canonical is None:
        return default_root_folder

    return "/".join([canonical] + parts[1:])


def normalize_metadata(data: dict, text: str, root_folders=None,
                       default_root_folder=None) -> dict:
    note_type = str(data.get("type", "note")).lower()
    
    if note_type not in TYPES:
        note_type = "note"

    title = (data.get("title") or text.strip()[:80]).strip() or text.strip()[:80]
    tags = [str(g).strip().lower() for g in (data.get("tags") or [])
            if str(g).strip()][:5]
    priority = str(data.get("priority", "low")).lower()

    if priority not in PRIORITIES:
        priority = "low"

    path = enforce_root(
      clean_path(data.get("path")) or default_root_folder, 
      root_folders, 
      default_root_folder)

    return {
        "type": note_type,
        "title": title,
        "path": path,
        "tags": tags,
        "priority": priority}


normalize = normalize_metadata
