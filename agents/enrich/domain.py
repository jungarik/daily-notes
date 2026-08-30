"""Self-contained domain + persistence for the enrichment agent.

Embeddings, the note/chunk SQL, the user's root-folder vocabulary, and the
one-shot enrichment LLM logic (+ normalization guardrails) — duplicated here so
`agents/enrich` depends on no shared domain layer (only infra: db, config, i18n,
openai_client).
"""

import json
import logging
from collections import Counter

from psycopg.types.json import Json

import config
import i18n
from db import cursor
from openai_client import get_client

logger = logging.getLogger(__name__)

TYPES = ("idea", "task", "reminder", "note", "question", "link")
PRIORITIES = ("low", "med", "high")


# ===== persistence =========================================================

def list_paths(user_id: int, limit: int = 30) -> list[tuple[str, int]]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT path, count(*) AS c FROM notes
            WHERE user_id = %s AND path IS NOT NULL AND path <> ''
            GROUP BY path ORDER BY c DESC, path LIMIT %s;
            """,
            (user_id, limit),
        )
        return [(r[0], r[1]) for r in cur.fetchall()]


def list_tags(user_id: int, limit: int = 30) -> list[tuple[str, int]]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT g, count(*) AS c
            FROM notes, jsonb_array_elements_text(tags) AS g
            WHERE user_id = %s GROUP BY g ORDER BY c DESC, g LIMIT %s;
            """,
            (user_id, limit),
        )
        return [(r[0], r[1]) for r in cur.fetchall()]


def set_metadata(note_id, note_type, title, priority, tags, path) -> None:
    with cursor() as cur:
        cur.execute(
            """
            UPDATE notes SET note_type = %s, title = %s, priority = %s, tags = %s, path = %s
            WHERE id = %s;
            """,
            (note_type, title, priority, Json(tags or []), path, note_id),
        )


def similar_notes(user_id: int, query_embedding: str, exclude_note_id: int,
                  limit: int = 5) -> list[dict]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT m.note_type, m.title, m.path, m.tags,
                   MIN(mc.embedding <=> %s::vector) AS distance
            FROM note_chunks mc JOIN notes m ON m.id = mc.note_id
            WHERE m.user_id = %s AND m.id <> %s AND m.title IS NOT NULL
            GROUP BY m.id, m.note_type, m.title, m.path, m.tags
            ORDER BY distance LIMIT %s;
            """,
            (query_embedding, user_id, exclude_note_id, limit),
        )
        return [{"note_type": r[0], "title": r[1], "path": r[2], "tags": r[3],
                 "distance": float(r[4])} for r in cur.fetchall()]


def language(user_id: int) -> str:
    """The user's UI language code ('en'/'uk'), or the default."""
    with cursor() as cur:
        cur.execute("SELECT language FROM users WHERE id = %s;", (user_id,))
        row = cur.fetchone()
    return i18n.normalize(row[0] if row else None) or i18n.DEFAULT_LOCALE


def localized_roots(user_id: int) -> tuple[dict[str, str], str]:
    """(root folders {translated name -> English meaning}, default folder name) in
    the user's language."""
    locale = language(user_id)
    roots = {i18n.t(locale, key): definition for key, definition in config.ROOT_FOLDERS.items()}
    default = i18n.t(locale, config.DEFAULT_ROOT_FOLDER_KEY)
    return roots, default


# ===== embeddings ==========================================================

def embed(text: str) -> str:
    resp = get_client().embeddings.create(model=config.EMBED_MODEL, input=text)
    return str(resp.data[0].embedding)


# ===== enrichment LLM + normalization ======================================

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


def root_folders_block(root_folders, default_root_folder) -> str:
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


def enrich(text: str, known_paths=None, known_tags=None, similar_notes=None,
           root_folders=None, default_root_folder=None) -> dict:
    """One-shot classification (fallback for the agent). Returns normalized
    {type, title, path, tags, priority}; degrades to a plain note on failure."""
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
            "reasoning (1-2 short sentences naming the note's topic and why this path "
            "and these tags — decide this first, before the other fields), "
            "type (one of: idea, task, reminder, note, question, link), "
            "title (a concise summary, <=8 words, in the note's own language), "
            "path (a single vault folder path: a root folder plus at most one "
            "sub-folder — two levels at most, forward slashes, no filename, no "
            "deeper nesting, e.g. Projects/telegram-bot or Areas/health), "
            "tags (0-5 lowercase topic keywords), "
            "priority (one of: low, med, high)."
            + root_folders_block(root_folders, default_root_folder)
            + _vocabulary(known_paths, known_tags)
            + neighbour_block
        )
        resp = get_client().chat.completions.create(
            model=config.ENRICH_LLM_MODEL, temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": text}])
        content = resp.choices[0].message.content
        logger.info("Enrichment | input=%r | response=%r", text, content)
        return normalize(json.loads(content), text, root_folders, default_root_folder)
    except Exception:
        logger.exception("Enrichment failed; storing as a plain note")
        return _fallback(text, default_root_folder)
