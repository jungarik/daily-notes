"""Agent tool registry.

Each tool wraps this package's self-contained `domain` module. A tool is its
OpenAI function schema (in TOOL_SPECS) plus a handler(ctx, args) -> str. Handlers
return a string the model reads back. `WRITE_TOOLS` names the tools that mutate
data and therefore require the user's confirmation before they run.
"""

import json
import logging

from agents.chat import domain as d

logger = logging.getLogger(__name__)


class Ctx:
    """Per-turn execution context passed to every tool. Carries the caller's
    identity + clock, and collects note citations the agent touched."""

    def __init__(self, user_id: int, now, tz=None, locale: str = "en"):
        self.user_id = user_id
        self.now = now
        self.tz = tz
        self.locale = locale
        self.citations: list[dict] = []
        self._cited: set[int] = set()

    def cite(self, note_id: int, title: str) -> None:
        if note_id in self._cited:
            return
        self._cited.add(note_id)
        self.citations.append({"note_id": note_id, "title": title or "note"})


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _label(title, text) -> str:
    """A human label for a citation chip: the note's title, else a text snippet."""
    t = (title or "").strip()
    if t:
        return t
    snip = " ".join((text or "").split())
    if not snip:
        return "note"
    return snip[:40] + "…" if len(snip) > 40 else snip


# ---- read tools -----------------------------------------------------------

def _search_notes(ctx: Ctx, args: dict) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "Error: query is required."
    ans, source_ids = d.answer_with_sources(
        ctx.user_id, query, ctx.now, language=ctx.locale, tz=ctx.tz)
    # Cite the distinct notes this answer drew on, in relevance order.
    briefs = {b["id"]: b for b in d.notes_brief(ctx.user_id, source_ids[:4])}
    for nid in source_ids[:4]:
        b = briefs.get(nid)
        if b:
            ctx.cite(nid, _label(b.get("title"), b.get("text")))
    return ans or "No relevant notes found."


def _get_note(ctx: Ctx, args: dict) -> str:
    nid = args.get("note_id")
    n = d.get_note_for_user(ctx.user_id, int(nid)) if nid is not None else None
    if not n:
        return "Error: note not found."
    ctx.cite(n["id"], _label(n.get("title"), n.get("text")))
    return _json({"id": n["id"], "title": n["title"], "path": n["path"],
                  "tags": n["tags"], "text": n["text"]})


def _neighbors(ctx: Ctx, args: dict) -> str:
    nid = args.get("note_id")
    if nid is None:
        return "Error: note_id is required."
    rows = d.links_of_for_user(ctx.user_id, int(nid))
    out = [{"id": r[0], "title": r[1] or "untitled", "direction": r[3]} for r in rows]
    return _json(out) if out else "No linked notes."


def _list_reminders(ctx: Ctx, args: dict) -> str:
    rows = d.upcoming(ctx.user_id)
    out = [{"id": r[0], "remind_at": r[1], "text": r[2], "status": r[3]} for r in rows]
    return _json(out) if out else "No upcoming reminders."


def _list_paths(ctx: Ctx, args: dict) -> str:
    return _json(d.known_paths(ctx.user_id))


# ---- write tools (confirmation required) ----------------------------------

def _create_reminder(ctx: Ctx, args: dict) -> str:
    text = (args.get("text") or "").strip()
    if not text:
        return "Error: text is required."
    note_id = d.capture_note(ctx.user_id, text)
    res = d.detect_reminder(note_id, ctx.user_id, text, ctx.now)
    if not res:
        return "Saved a note, but no time could be parsed — ask the user when to remind them."
    rid, remind_at = res
    return _json({"reminder_id": rid, "remind_at": remind_at})


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


HANDLERS = {
    "search_notes": _search_notes,
    "get_note": _get_note,
    "neighbors": _neighbors,
    "list_reminders": _list_reminders,
    "list_paths": _list_paths,
    "create_reminder": _create_reminder,
    "set_note_path": _set_note_path,
}

WRITE_TOOLS = {"create_reminder", "set_note_path"}


def summarize_write(name: str, args: dict) -> str:
    """A human-readable one-liner for the confirmation prompt."""
    if name == "create_reminder":
        return "Create a reminder: “%s”." % (args.get("text", "").strip())
    if name == "set_note_path":
        return "Move note %s to “%s”." % (args.get("note_id"), args.get("path", "").strip())
    return "Run %s with %s." % (name, args)


def execute_tool(ctx: Ctx, name: str, args: dict) -> str:
    fn = HANDLERS.get(name)
    if not fn:
        return "Error: unknown tool %s." % name
    logger.info("agent tool %s user=%s args=%s", name, ctx.user_id, args)
    try:
        return fn(ctx, args or {})
    except Exception as exc:
        logger.exception("agent tool %s failed", name)
        return "Error running %s: %s" % (name, exc)


def _fn(name, description, properties, required):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }}


TOOL_SPECS = [
    _fn("search_notes",
        "Semantic search + RAG over the user's own notes. Use this first to find "
        "relevant notes or answer questions about what they've written.",
        {"query": {"type": "string", "description": "Natural-language search query."}},
        ["query"]),
    _fn("get_note", "Fetch one note's full detail (title, path, tags, text) by id.",
        {"note_id": {"type": "integer"}}, ["note_id"]),
    _fn("neighbors", "List the notes directly linked to a given note (its connections).",
        {"note_id": {"type": "integer"}}, ["note_id"]),
    _fn("list_reminders", "List the user's upcoming (active) reminders.", {}, []),
    _fn("list_paths", "List the user's existing folder paths (the vault vocabulary).", {}, []),
    _fn("create_reminder",
        "Create a reminder from a natural-language instruction that includes a time "
        "(e.g. 'remind me to call Bob tomorrow at 5pm'). Requires user confirmation.",
        {"text": {"type": "string"}}, ["text"]),
    _fn("set_note_path",
        "Move a note to a different vault path (must start with a root folder). "
        "Requires user confirmation.",
        {"note_id": {"type": "integer"}, "path": {"type": "string"}}, ["note_id", "path"]),
]
