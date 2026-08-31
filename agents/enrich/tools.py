"""Enrichment/action agent tool registry.

The enrich agent can create notes, move notes and classify (enrich) them — with a confirmation step before each
write. Read tools (existing paths/tags) give it vocabulary/context. Each tool is
its OpenAI function schema (in TOOL_SPECS) plus a handler(ctx, args) -> str.
`WRITE_TOOLS` names the tools that mutate data and require the user's confirmation.
"""

import json
import logging

from agents.enrich import domain as d
from agents.enrich import db

logger = logging.getLogger(__name__)


class Ctx:
    """Per-turn execution context: the caller's identity + clock/locale."""

    def __init__(self, user_id: int, now, tz=None, locale: str = "en"):
        self.user_id = user_id
        self.now = now
        self.tz = tz
        self.locale = locale


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


# ---- read tools (context) -------------------------------------------------

def _list_paths(ctx: Ctx, args: dict) -> str:
    rows = db.list_paths(ctx.user_id)
    return _json([{"path": p, "count": c} for p, c in rows]) if rows else "No existing paths."


def _list_tags(ctx: Ctx, args: dict) -> str:
    rows = db.list_tags(ctx.user_id)
    return _json([{"tag": t, "count": c} for t, c in rows]) if rows else "No existing tags."


# ---- write tools (confirmation required) ----------------------------------

def _create_note(ctx: Ctx, args: dict) -> str:
    text = (args.get("text") or "").strip()
    if not text:
        return "Error: text is required."
    note_id = d.capture_note(ctx.user_id, text)
    return _json({"note_id": note_id})


def _set_note_path(ctx: Ctx, args: dict) -> str:
    nid, path = args.get("note_id"), (args.get("path") or "").strip()
    if nid is None or not path:
        return "Error: note_id and path are required."
    status, meta = d.move_note(ctx.user_id, int(nid), path)
    if status == "invalid":
        return "Error: path must start with a root folder."
    if status == "not_found":
        return "Error: note not found."
    return _json({"ok": True, "path": (meta or {}).get("path")})


def _enrich_note(ctx: Ctx, args: dict) -> str:
    nid = args.get("note_id")
    if nid is None:
        return "Error: note_id is required."
    meta = d.enrich_note(ctx.user_id, int(nid))
    if meta is None:
        return "Error: note not found or empty."
    return _json(meta)


HANDLERS = {
    "list_paths": _list_paths,
    "list_tags": _list_tags,
    "create_note": _create_note,
    "set_note_path": _set_note_path,
    "enrich_note": _enrich_note,
}

WRITE_TOOLS = {"create_note", "set_note_path", "enrich_note"}


def summarize_write(name: str, args: dict) -> str:
    """A human-readable one-liner for the confirmation prompt."""
    if name == "create_note":
        return "Create a note: “%s”." % (args.get("text", "").strip())
    if name == "set_note_path":
        return "Move note %s to “%s”." % (args.get("note_id"), args.get("path", "").strip())
    if name == "enrich_note":
        return "Enrich note %s (classify type/title/path/tags)." % args.get("note_id")
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


def _fn(name, description, properties, required):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }}


TOOL_SPECS = [
    _fn("list_paths", "List the user's existing vault folder paths (with counts), "
        "so you reuse one instead of inventing a parallel path.", {}, []),
    _fn("list_tags", "List the user's existing tags (with counts) so you can reuse them.", {}, []),
    _fn("create_note",
        "Create a new note from the given text (chunked + embedded). Requires user "
        "confirmation.", {"text": {"type": "string"}}, ["text"]),
    _fn("set_note_path",
        "Move a note to a different vault path (must start with a root folder). "
        "Requires user confirmation.",
        {"note_id": {"type": "integer"}, "path": {"type": "string"}}, ["note_id", "path"]),
    _fn("enrich_note",
        "Classify a note and fill in its metadata (type, title, vault path, tags, "
        "priority) with the one-shot enricher. Requires user confirmation.",
        {"note_id": {"type": "integer"}}, ["note_id"]),
]
