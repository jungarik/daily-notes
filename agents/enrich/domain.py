"""Domain logic for the enrichment/action agent (no raw SQL; that lives in db.py).

Everything the agent's tools do — create a note (chunk + embed), move a note,
and classify/enrich a note (one-shot LLM + guardrails) —
over the agent's own `db` + shared infra (config, i18n, openai_client). No shared
domain layer.
"""

import json
import logging
from collections import Counter

import config
import i18n
from openai_client import get_client
from agents.enrich import db

logger = logging.getLogger(__name__)

TYPES = ("idea", "task", "reminder", "note", "question", "link")
PRIORITIES = ("low", "med", "high")


# ===== user language + roots ===============================================

def language(user_id: int) -> str:
    return i18n.normalize(db.get_language(user_id)) or i18n.DEFAULT_LOCALE


def localized_roots(user_id: int) -> tuple[dict[str, str], str]:
    locale = language(user_id)
    roots = {i18n.t(locale, key): definition for key, definition in config.ROOT_FOLDERS.items()}
    default = i18n.t(locale, config.DEFAULT_ROOT_FOLDER_KEY)
    return roots, default


def _all_root_names() -> set[str]:
    return {i18n.t(loc, key) for key in config.ROOT_FOLDERS for loc in i18n.SUPPORTED}


def clean_root_path(path: str) -> str | None:
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


def embed(text: str) -> str:
    resp = get_client().embeddings.create(model=config.EMBED_MODEL, input=text)
    return str(resp.data[0].embedding)


def _build_chunks(text: str) -> list[dict]:
    return [{"index": i, "content": c, "token_count": len(c.split()),
             "metadata": {"char_len": len(c)}, "embedding": embed(c)}
            for i, c in enumerate(_chunk_text(text))]


# ===== note capture (create_note tool) =====================================

def capture_note(user_id: int, text: str) -> int:
    """Persist a text note (chunk + embed). Text-only (the agent captures no media)."""
    note_id = db.save_note(user_id, text)
    db.save_chunks(note_id, _build_chunks(text))
    logger.info("Enrich agent captured note %s (user %s)", note_id, user_id)
    return note_id


# ===== move (set_note_path tool) ===========================================

def move_note(user_id: int, note_id: int, raw_path: str) -> tuple[str, dict | None]:
    cleaned = clean_root_path(raw_path)
    if cleaned is None:
        return ("invalid", None)
    if db.get_note_for_user(user_id, note_id) is None:
        return ("not_found", None)
    db.set_path(note_id, cleaned)
    return ("ok", db.get_meta(note_id))


# ===== enrichment LLM + normalization (enrich_note tool) ===================

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


def _fallback(text: str, default_root_folder: str | None = None) -> dict:
    return {"type": "note", "title": text.strip()[:80], "path": default_root_folder,
            "tags": [], "priority": "low"}


def _root_folders_block(root_folders, default_root_folder) -> str:
    if not root_folders:
        return ""
    names = ", ".join(root_folders)
    meanings = "; ".join(f"{name} — {desc}" for name, desc in root_folders.items())
    return (
        f" The path is core to the vault: any path starts with exactly one of these "
        f"root folders — {names} — followed by at most one sub-folder, so a path is "
        f"one or two levels total (e.g. Projects/telegram-bot or Areas/health). Never "
        f"nest deeper than two levels. Root folder meanings: {meanings}. Pick the "
        f"root folder matching the note's purpose, and reuse an existing path when "
        f"one fits. If you cannot determine a path, use {default_root_folder}."
    )


def _fmt_vocab(items) -> str:
    out = []
    for it in items:
        if isinstance(it, (list, tuple)) and len(it) == 2:
            out.append(f"{it[0]} ({it[1]})")
        else:
            out.append(str(it))
    return ", ".join(out)


def _vocabulary(known_paths, known_tags) -> str:
    lines = []
    if known_paths:
        lines.append(f"Existing paths (with note use counts): {_fmt_vocab(known_paths)}.")
    if known_tags:
        lines.append(f"Existing tags (with use counts): {_fmt_vocab(known_tags)}.")
    if not lines:
        return ""
    return (
        " Reuse an existing path/tag verbatim when it genuinely fits (extend a path "
        "rather than inventing a parallel one); only create a new one if none apply. "
        + " ".join(lines)
    )


def _neighbour_hint(neighbours) -> str:
    paths, tags = Counter(), Counter()
    for n in neighbours:
        if n.get("path"):
            paths[n["path"]] += 1
        for tg in (n.get("tags") or []):
            tags[tg] += 1
    if not paths and not tags:
        return ""
    parts = []
    if paths:
        parts.append("filed under: " + ", ".join(f"{p} ({c})" for p, c in paths.most_common(5)))
    if tags:
        parts.append("commonly tagged: " + ", ".join(f"{t} ({c})" for t, c in tags.most_common(8)))
    return " Notes most similar to this one are " + "; ".join(parts) + ". Prefer these when they fit."


def _similar(similar_notes_list) -> str:
    if not similar_notes_list:
        return ""
    lines = [f"- \"{n['title']}\" -> type={n['note_type']}, path={n.get('path')}, "
             f"tags={n.get('tags') or []}" for n in similar_notes_list]
    return (" Similar past notes and how they were classified (reuse their type / "
            "path / tags when appropriate):\n" + "\n".join(lines))


def _enrich(text, known_paths, known_tags, similar_notes, root_folders, default_root) -> dict:
    try:
        neighbours = similar_notes or []
        threshold = config.ENRICH_SIMILAR_MAX_DISTANCE
        has_dist = any(n.get("distance") is not None for n in neighbours)
        strong = ([n for n in neighbours if n.get("distance") is not None and n["distance"] <= threshold]
                  if has_dist else neighbours)
        if strong:
            neighbour_block = _neighbour_hint(strong) + _similar(strong)
        elif neighbours:
            neighbour_block = (" None of the user's existing notes are closely related to this one, "
                               "so do not force-fit an existing path — prefer a default folder, and "
                               "create a new path only if clearly warranted.")
        else:
            neighbour_block = ""
        system = (
            "You organize a person's brain-dump notes (Ukrainian or English) into "
            "an PARA-style vault (i.e. Obsidian-style)."
            "Classify the note and extract metadata. Return strict JSON with keys: "
            "reasoning (1-2 short sentences), "
            "type (one of: idea, task, reminder, note, question, link), "
            "title (a concise summary, <=8 words, in the note's own language), "
            "path (a single vault folder path: a root folder plus at most one "
            "sub-folder — two levels at most), "
            "tags (0-5 lowercase topic keywords), priority (one of: low, med, high)."
            + _root_folders_block(root_folders, default_root) + _vocabulary(known_paths, known_tags)
            + neighbour_block)
        resp = get_client().chat.completions.create(
            model=config.ENRICH_LLM_MODEL, temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": text}])
        return normalize(json.loads(resp.choices[0].message.content), text, root_folders, default_root)
    except Exception:
        logger.exception("Enrichment failed; storing as a plain note")
        return _fallback(text, default_root)


def enrich_note(user_id: int, note_id: int) -> dict | None:
    """Classify a note and persist its metadata. Returns the metadata, or None if
    the note has no text."""
    text = db.get_text(note_id)
    if not text:
        return None
    embedding = embed(text)
    similar = db.similar_notes(user_id, embedding, exclude_note_id=note_id,
                               limit=config.ENRICH_SIMILAR_LIMIT)
    root_folders, default_root = localized_roots(user_id)
    meta = _enrich(text, db.list_paths(user_id), db.list_tags(user_id),
                   similar, root_folders, default_root)
    db.set_metadata(note_id, meta["type"], meta["title"], meta["priority"],
                    meta["tags"], meta["path"])
    logger.info("Enriched note %s -> %s '%s' @ %s", note_id, meta["type"], meta["title"], meta["path"])
    return meta
