"""
Note enrichment: one LLM call that turns a raw brain-dump note into structured
metadata — type, title, a vault path, tags, priority.

Runs on demand (the 🧠 Enrich button), with the chat's existing path/tag
vocabulary and similar past notes as context so classification stays consistent.
On any failure it degrades gracefully to a plain note.
"""

import json
import logging
from datetime import datetime

import config
from openai_client import get_client

logger = logging.getLogger(__name__)

TYPES = ("idea", "task", "reminder", "note", "question", "link")
PRIORITIES = ("low", "med", "high")


def _fallback(text: str, default_path: str | None = None) -> dict:
    return {
        "type": "note",
        "title": text.strip()[:80],
        "path": default_path,
        "tags": [],
        "priority": "low",
    }


def _clean_path(raw) -> str | None:
    if not raw:
        return None
    parts = [p.strip() for p in str(raw).replace("\\", "/").split("/")]
    parts = [p for p in parts if p and p not in (".", "..")]
    return "/".join(parts) or None


def _normalize(data: dict, text: str, default_path: str | None = None) -> dict:
    note_type = str(data.get("type", "note")).lower()
    if note_type not in TYPES:
        note_type = "note"

    title = (data.get("title") or text.strip()[:80]).strip() or text.strip()[:80]

    tags = [str(g).strip().lower() for g in (data.get("tags") or []) if str(g).strip()][:5]

    priority = str(data.get("priority", "low")).lower()
    if priority not in PRIORITIES:
        priority = "low"

    # If the model couldn't settle on a path, fall back to the default folder.
    path = _clean_path(data.get("path")) or default_path

    return {
        "type": note_type,
        "title": title,
        "path": path,
        "tags": tags,
        "priority": priority,
    }


def _vocabulary(known_paths, known_tags) -> str:
    """A prompt block nudging the model to reuse existing paths/tags."""
    lines = []
    if known_paths:
        lines.append(f"Existing paths: {', '.join(known_paths)}.")
    if known_tags:
        lines.append(f"Existing tags: {', '.join(known_tags)}.")
    if not lines:
        return ""
    return (
        " Reuse an existing path/tag verbatim when it fits (extend a path rather "
        "than inventing a parallel one); only create a new one if none apply. "
        + " ".join(lines)
    )


def _defaults(default_paths, default_path) -> str:
    """A prompt block offering the predefined default folders as a fallback set."""
    if not default_paths:
        return ""
    return (
        f" If no existing path fits, pick one of these default top-level folders: "
        f"{', '.join(default_paths)}. If you still cannot determine a path, use "
        f"{default_path}."
    )


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
           default_paths=None, default_path=None) -> dict:
    """Classify + extract metadata for a note. Returns a normalized dict:
    {type, title, path, tags, priority}.

    Path vocabulary has two parts the model weighs together: `known_paths` (the
    user's existing DB paths) and `default_paths` (predefined default folders).
    It reuses an existing path when one fits, otherwise picks a default; if it
    can't decide at all, the path falls back to `default_path`. `known_tags` and
    `similar_notes` keep the rest of the classification consistent.
    """
    try:
        system = (
            "You organize a person's brain-dump notes (Ukrainian or English) into "
            "an Obsidian-style vault. Classify the note and extract metadata. "
            "Return strict JSON with keys: "
            "type (one of: idea, task, reminder, note, question, link), "
            "title (a concise summary, <=8 words, in the note's own language), "
            "path (a single vault folder path — forward slashes, no filename, e.g. "
            "projects/telegram-bot or areas/health), "
            "tags (0-5 lowercase topic keywords), "
            "priority (one of: low, med, high)."
            + _vocabulary(known_paths, known_tags)
            + _defaults(default_paths, default_path)
            + _similar(similar_notes)
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
        logger.info("Enrichment | input=%r | response=%s", text, content)
        return _normalize(json.loads(content), text, default_path)
    except Exception:
        logger.exception("Enrichment failed; storing as a plain note")
        return _fallback(text, default_path)
