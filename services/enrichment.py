"""
Note enrichment: one LLM call that turns a raw brain-dump note into structured
metadata — type, title, a vault path, tags, priority.

Runs on demand (the 🧠 Enrich button), with the chat's existing path/tag
vocabulary and similar past notes as context so classification stays consistent.
On any failure it degrades gracefully to a plain note.
"""

import json
import logging
from collections import Counter
from datetime import datetime

import config
from openai_client import get_client

logger = logging.getLogger(__name__)

TYPES = ("idea", "task", "reminder", "note", "question", "link")
PRIORITIES = ("low", "med", "high")


def _fallback(text: str, default_root_folder: str | None = None) -> dict:
    return {
        "type": "note",
        "title": text.strip()[:80],
        "path": default_root_folder,
        "tags": [],
        "priority": "low",
    }


def _clean_path(raw) -> str | None:
    if not raw:
        return None
    parts = [p.strip() for p in str(raw).replace("\\", "/").split("/")]
    parts = [p for p in parts if p and p not in (".", "..")]
    return "/".join(parts) or None


def _normalize(data: dict, text: str, default_root_folder: str | None = None) -> dict:
    note_type = str(data.get("type", "note")).lower()
    if note_type not in TYPES:
        note_type = "note"

    title = (data.get("title") or text.strip()[:80]).strip() or text.strip()[:80]

    tags = [str(g).strip().lower() for g in (data.get("tags") or []) if str(g).strip()][:5]

    priority = str(data.get("priority", "low")).lower()
    if priority not in PRIORITIES:
        priority = "low"

    # If the model couldn't settle on a path, fall back to the default folder.
    path = _clean_path(data.get("path")) or default_root_folder

    return {
        "type": note_type,
        "title": title,
        "path": path,
        "tags": tags,
        "priority": priority,
    }

def _root_folders(root_folders, default_root_folder) -> str:
    """The core path rule + folder meanings + fallback, in one block.

    Every path must start with exactly one of the predefined root folders; the
    mapping gives each folder's purpose so the model classifies by meaning, not
    by lexical similarity.
    """
    if not root_folders:
        return ""
    names = ", ".join(root_folders)
    meanings = "; ".join(f"{name} — {desc}" for name, desc in root_folders.items())
    return (
        f" The path is core to the vault: any path starts with exactly one of these "
        f"root folders — {names} — and MUST be followed by sub-folders "
        f"(e.g. Projects/telegram-bot). Root folder meanings: {meanings}. Pick the "
        f"root folder matching the note's purpose, and reuse an existing path when "
        f"one fits. If you cannot determine a path, use {default_root_folder}."
    )


def _fmt_vocab(items) -> str:
    """Render a vocabulary list; each item is a name or a (name, count) pair."""
    out = []
    for it in items:
        if isinstance(it, (list, tuple)) and len(it) == 2:
            out.append(f"{it[0]} ({it[1]})")
        else:
            out.append(str(it))
    return ", ".join(out)

def _vocabulary(known_paths, known_tags) -> str:
    """A prompt block nudging the model to reuse existing paths/tags (with counts)."""
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
    """Aggregate the closest notes into an explicit path/tag suggestion."""
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


def _similar(similar_notes) -> str:
    """A few-shot block: how similar past notes were classified (for consistency)."""
    if not similar_notes:
        return ""
    lines = [
        f"- \"{n['title']}\" -> type={n['note_type']}, "
        f"path={n.get('path')}, tags={n.get('tags') or []}"
        for n in similar_notes
    ]
    return (
        " Similar past notes and how they were classified (reuse their type / "
        "path / tags when appropriate):\n" + "\n".join(lines)
    )


def enrich(text: str, known_paths=None, known_tags=None, similar_notes=None,
           root_folders=None, default_root_folder=None) -> dict:
    """Classify + extract metadata for a note. Returns a normalized dict:
    {type, title, path, tags, priority}.

    Path vocabulary has two parts the model weighs together: `known_paths` (the
    user's existing DB paths) and `root_folders` (the predefined root folders as a
    {folder: meaning} mapping). It reuses an existing path when one fits, otherwise
    picks a root folder; if it can't decide at all, the path falls back to
    `default_root_folder`. `known_tags` and `similar_notes` keep the rest of the
    classification consistent.
    """
    try:
        # Partition neighbours by closeness: strong ones drive the suggestion and
        # few-shot; if none are close, tell the model not to force-fit a path.
        neighbours = similar_notes or []
        threshold = config.ENRICH_SIMILAR_MAX_DISTANCE
        has_dist = any(n.get("distance") is not None for n in neighbours)
        strong = (
            [n for n in neighbours if n.get("distance") is not None and n["distance"] <= threshold]
            if has_dist else neighbours
        )
        if strong:
            neighbour_block = _neighbour_hint(strong) + _similar(strong)
        elif neighbours:
            neighbour_block = (
                " None of the user's existing notes are closely related to this one, "
                "so do not force-fit an existing path — prefer a default folder, and "
                "create a new path only if clearly warranted."
            )
        else:
            neighbour_block = ""

        system = (
            "You organize a person's brain-dump notes (Ukrainian or English) into "
            "an Obsidian-style vault. Classify the note and extract metadata. "
            "Return strict JSON with keys: "
            "reasoning (1-2 short sentences naming the note's topic and why this path "
            "and these tags — decide this first, before the other fields), "
            "type (one of: idea, task, reminder, note, question, link), "
            "title (a concise summary, <=8 words, in the note's own language), "
            "path (a single vault folder path that starts with a root folder — "
            "forward slashes, no filename, e.g. Projects/telegram-bot or Areas/health), "
            "tags (0-5 lowercase topic keywords), "
            "priority (one of: low, med, high)."
            + _root_folders(root_folders, default_root_folder)
            + _vocabulary(known_paths, known_tags)
            + neighbour_block
        )
        resp = get_client().chat.completions.create(
            model=config.ENRICH_LLM_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
        )
        content = resp.choices[0].message.content
        logger.info(
            "Enrichment | input=%r | system=%r | response=%r",
            text, system, content,
        )
        return _normalize(json.loads(content), text, default_root_folder)
    except Exception:
        logger.exception("Enrichment failed; storing as a plain note")
        return _fallback(text, default_root_folder)

