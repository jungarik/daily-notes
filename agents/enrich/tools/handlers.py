"""Execution handlers for enrichment read and write tools."""

import json
import logging
import re
from datetime import datetime

import config
import i18n
from common import embedings
from common import helper
from agents.enrich.tools import db

logger = logging.getLogger(__name__)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…。！？])\s+")


class Ctx:
    def __init__(self, user_id: int, now, tz=None, locale: str = "en"):
        self.user_id = user_id
        self.now = now
        self.tz = tz
        self.locale = locale


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _embed(text: str) -> str:
    return embedings.embed(text)


def _atomic_note_text(text: str) -> str:
    value = " ".join(line.strip() for line in str(text or "").splitlines()
                     if line.strip())
    if not value:
        return ""
    sentences = _SENTENCE_SPLIT.split(value)
    value = " ".join(sentences[:config.ATOMIC_NOTE_MAX_SENTENCES]).strip()
    if len(value) <= config.ATOMIC_NOTE_MAX_CHARS:
        return value
    shortened = value[:config.ATOMIC_NOTE_MAX_CHARS].rsplit(" ", 1)[0].strip()
    return shortened.rstrip(" ,.;:-") + "..."


def _all_root_names() -> set[str]:
    return {i18n.t(locale, key)
            for key in config.ROOT_FOLDERS for locale in i18n.SUPPORTED}


def _clean_root_path(path: str) -> str | None:
    if not path:
        return None
    parts = [part.strip() for part in str(path).replace("\\", "/").split("/")]
    parts = [part for part in parts if part and part not in (".", "..")]
    if not parts:
        return None
    roots = {name.lower(): name for name in _all_root_names()}
    canonical = roots.get(parts[0].lower())
    if canonical is None:
        return None
    return "/".join([canonical] + parts[1:])


def _list_paths(ctx: Ctx, _args: dict) -> str:
    rows = db.list_paths(ctx.user_id)
    return _json([{"path": p, "count": c} for p, c in rows]) if rows else "No existing paths."


def _list_tags(ctx: Ctx, _args: dict) -> str:
    rows = db.list_tags(ctx.user_id)
    return _json([{"tag": t, "count": c} for t, c in rows]) if rows else "No existing tags."


def _get_note_context(ctx: Ctx, args: dict) -> str:
    note_id = args.get("note_id")
    if note_id is None:
        return "Error: note_id is required."
    note = db.get_note_for_user(ctx.user_id, int(note_id))
    return _json(note) if note else "Error: note not found."


def _get_vault_context(ctx: Ctx, _args: dict) -> str:
    roots, default_root = helper.localized_root_folders(db.get_language(ctx.user_id))
    return _json({"root_folders": roots, "default_root": default_root})


def _find_related_notes(ctx: Ctx, args: dict) -> str:
    text = (args.get("text") or "").strip()
    if not text:
        return "Error: text is required."
    embedding = _embed(text)
    note_id = args.get("exclude_note_id")
    rows = (db.similar_notes(ctx.user_id, embedding, int(note_id),
                             limit=config.ENRICH_SIMILAR_LIMIT)
            if note_id is not None else
            db.related_notes(ctx.user_id, embedding, config.ENRICH_SIMILAR_LIMIT))
    return _json(rows)


def _create_note(ctx: Ctx, args: dict) -> str:
    text = _atomic_note_text(args.get("text") or "")
    if not text:
        return "Error: text is required."
    note_id = db.save_note(ctx.user_id, text)
    db.save_chunks(note_id, embedings.build_chunks(text))
    logger.info("Enrich agent captured note %s (user %s)", note_id, ctx.user_id)
    return _json({"note_id": note_id})


def _set_note_path(ctx: Ctx, args: dict) -> str:
    note_id, path = args.get("note_id"), (args.get("path") or "").strip()
    if note_id is None or not path:
        return "Error: note_id and path are required."
    cleaned = _clean_root_path(path)
    if cleaned is None:
        return "Error: path must start with a root folder."
    note_id = int(note_id)
    if db.get_note_for_user(ctx.user_id, note_id) is None:
        return "Error: note not found."
    db.set_path(note_id, cleaned)
    meta = db.get_meta(note_id)
    return _json({"ok": True, "path": (meta or {}).get("path")})


def _enrich_note(ctx: Ctx, args: dict) -> str:
    note_id = args.get("note_id")
    if note_id is None:
        return "Error: note_id is required."
    required = {"type", "title", "path", "tags", "priority"}
    if not required.issubset(args):
        return "Error: enrichment proposal is missing approved metadata; regenerate it."
    note_id = int(note_id)
    note = db.get_note_for_user(ctx.user_id, note_id)
    if not note or not (note.get("text") or "").strip():
        return "Error: note not found or empty."
    root_folders, default_root = helper.localized_root_folders(db.get_language(ctx.user_id))
    metadata = helper.normalize(args, note["text"], root_folders, default_root)
    db.set_metadata(note_id, metadata["type"], metadata["title"],
                    metadata["priority"], metadata["tags"], metadata["path"])
    logger.info("Enriched note %s -> %s '%s' @ %s", note_id,
                metadata["type"], metadata["title"], metadata["path"])
    return _json(metadata)


def _create_reminder(ctx: Ctx, args: dict) -> str:
    text = (args.get("text") or "").strip()
    raw_time = args.get("remind_at")
    if not text or not raw_time:
        return "Error: text and remind_at are required."
    remind_at = datetime.fromisoformat(raw_time)
    note_id = args.get("note_id")
    if note_id is None:
        note_text = _atomic_note_text(text)
        note_id = db.save_note(ctx.user_id, note_text)
        db.save_chunks(note_id, embedings.build_chunks(note_text))
        logger.info("Enrich created backing note %s for reminder (user %s)",
                    note_id, ctx.user_id)
    else:
        note_id = int(note_id)
    reminder_id = db.attach_reminder(ctx.user_id, note_id, remind_at)
    result = ({"note_id": note_id, "reminder_id": reminder_id,
               "remind_at": remind_at.isoformat()}
              if reminder_id is not None else None)
    return _json(result) if result is not None else "Error: referenced note not found."


HANDLERS = {
    "list_paths": _list_paths, 
    "list_tags": _list_tags,
    "get_note_context": _get_note_context, 
    "get_vault_context": _get_vault_context,
    "find_related_notes": _find_related_notes,
    "create_note": _create_note,
    "set_note_path": _set_note_path, 
    "enrich_note": _enrich_note,
    "create_reminder": _create_reminder,
}

METADATA_CONTEXT_TOOLS = {
    "get_note_context", "list_paths", "list_tags",
    "get_vault_context", "find_related_notes",
}


def summarize_write(name: str, args: dict) -> str:
    if name == "create_note":
        return "Create a note: “%s”." % args.get("text", "").strip()
    if name == "set_note_path":
        return "Move note %s to “%s”." % (args.get("note_id"), args.get("path", "").strip())
    if name == "enrich_note":
        if args.get("title"):
            return "Apply metadata to note %s: “%s” (%s) at “%s”, tags %s." % (
                args.get("note_id"), args.get("title"), args.get("type"),
                args.get("path"), args.get("tags") or [])
        return "Enrich note %s (classify type/title/path/tags)." % args.get("note_id")
    if name == "create_reminder":
        return "Create a reminder for %s: “%s”." % (
            args.get("remind_at"), (args.get("text") or "").strip())
    return "Run %s with %s." % (name, args)


def execute_tool(ctx: Ctx, name: str, args: dict) -> str:
    fn = HANDLERS.get(name)
    if not fn:
        return "Error: unknown tool %s." % name
    logger.info("enrich tool %s user=%s args=%s", name, ctx.user_id, args)
    try:
        return fn(ctx, args or {})
    except Exception as exc:
        logger.exception("enrich tool %s failed", name)
        return "Error running %s: %s" % (name, exc)


def execute_context_tool(ctx: Ctx, name: str, args: dict) -> str:
    """Execute a mandatory metadata-context tool not selected by the LLM."""
    if name not in METADATA_CONTEXT_TOOLS:
        raise ValueError("Not a metadata context tool: %s" % name)
    return execute_tool(ctx, name, args)
