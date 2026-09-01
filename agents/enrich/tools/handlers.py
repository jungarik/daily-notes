"""Execution handlers for enrichment read and write tools."""

import json
import logging
from datetime import datetime

import config
from agents.enrich import domain as d
from agents.enrich import db

logger = logging.getLogger(__name__)


class Ctx:
    def __init__(self, user_id: int, now, tz=None, locale: str = "en"):
        self.user_id = user_id
        self.now = now
        self.tz = tz
        self.locale = locale


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


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
    roots, default_root = d.localized_roots(ctx.user_id)
    return _json({"root_folders": roots, "default_root": default_root})


def _find_related_notes(ctx: Ctx, args: dict) -> str:
    text = (args.get("text") or "").strip()
    if not text:
        return "Error: text is required."
    embedding = d.embed(text)
    note_id = args.get("exclude_note_id")
    rows = (db.similar_notes(ctx.user_id, embedding, int(note_id),
                             limit=config.ENRICH_SIMILAR_LIMIT)
            if note_id is not None else
            db.related_notes(ctx.user_id, embedding, config.ENRICH_SIMILAR_LIMIT))
    return _json(rows)


def _create_note(ctx: Ctx, args: dict) -> str:
    text = (args.get("text") or "").strip()
    if not text:
        return "Error: text is required."
    return _json({"note_id": d.capture_note(ctx.user_id, text)})


def _set_note_path(ctx: Ctx, args: dict) -> str:
    note_id, path = args.get("note_id"), (args.get("path") or "").strip()
    if note_id is None or not path:
        return "Error: note_id and path are required."
    status, meta = d.move_note(ctx.user_id, int(note_id), path)
    if status == "invalid":
        return "Error: path must start with a root folder."
    if status == "not_found":
        return "Error: note not found."
    return _json({"ok": True, "path": (meta or {}).get("path")})


def _enrich_note(ctx: Ctx, args: dict) -> str:
    note_id = args.get("note_id")
    if note_id is None:
        return "Error: note_id is required."
    required = {"type", "title", "path", "tags", "priority"}
    if not required.issubset(args):
        return "Error: enrichment proposal is missing approved metadata; regenerate it."
    meta = d.enrich_note(ctx.user_id, int(note_id), args)
    return _json(meta) if meta is not None else "Error: note not found or empty."


def _create_reminder(ctx: Ctx, args: dict) -> str:
    text = (args.get("text") or "").strip()
    raw_time = args.get("remind_at")
    if not text or not raw_time:
        return "Error: text and remind_at are required."
    remind_at = datetime.fromisoformat(raw_time)
    note_id = args.get("note_id")
    result = (d.attach_reminder(ctx.user_id, int(note_id), remind_at)
              if note_id is not None
              else d.create_reminder(ctx.user_id, text, remind_at))
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
