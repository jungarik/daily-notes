"""Shared deterministic helpers for the enrichment/action agent."""

import config
import i18n
from openai_client import get_client
from agents.enrich import db

TYPES = ("idea", "task", "reminder", "note", "question", "link")
PRIORITIES = ("low", "med", "high")

# ===== user language + roots ===============================================

def _language(user_id: int) -> str:
    return i18n.normalize(db.get_language(user_id)) or i18n.DEFAULT_LOCALE


def localized_roots(user_id: int) -> tuple[dict[str, str], str]:
    locale = _language(user_id)
    roots = {i18n.t(locale, key): definition for key, definition in config.ROOT_FOLDERS.items()}
    default = i18n.t(locale, config.DEFAULT_ROOT_FOLDER_KEY)
    return roots, default


# ===== embeddings ==========================================================

def _chunk_text(text: str, size: int = config.CHUNK_SIZE, overlap: int = config.CHUNK_OVERLAP):
    text = text.strip()
    if len(text) <= size:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + size])
        start += size - overlap
    return chunks


def _embed(text: str) -> str:
    resp = get_client().embeddings.create(model=config.EMBED_MODEL, input=text)
    return str(resp.data[0].embedding)


def _build_chunks(text: str) -> list[dict]:
    return [{"index": i, "content": c, "token_count": len(c.split()),
             "metadata": {"char_len": len(c)}, "embedding": _embed(c)}
            for i, c in enumerate(_chunk_text(text))]


# ===== metadata normalization and deterministic persistence ================

def _clean_path(raw) -> str | None:
    if not raw:
        return None
    parts = [p.strip() for p in str(raw).replace("\\", "/").split("/")]
    parts = [p for p in parts if p and p not in (".", "..")][:2]
    return "/".join(parts) or None


def _enforce_root(path, root_folders, default_root_folder):
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


def normalize(data: dict, text: str, root_folders=None, default_root_folder=None) -> dict:
    note_type = str(data.get("type", "note")).lower()
    if note_type not in TYPES:
        note_type = "note"
    title = (data.get("title") or text.strip()[:80]).strip() or text.strip()[:80]
    tags = [str(g).strip().lower() for g in (data.get("tags") or []) if str(g).strip()][:5]
    priority = str(data.get("priority", "low")).lower()
    if priority not in PRIORITIES:
        priority = "low"
    path = _clean_path(data.get("path")) or default_root_folder
    path = _enforce_root(path, root_folders, default_root_folder)
    return {"type": note_type, "title": title, "path": path, "tags": tags, "priority": priority}
