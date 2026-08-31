"""Chat agent tool registry.

Read tools wrap this package's `domain` (logic) or `db` (reads). The chat agent
does no writes itself: when the user asks to create/change something it calls the
handoff tools, which the loop routes to the appropriate specialist for planning
+ a confirmation step — the chat agent never mutates data directly.
A tool is its OpenAI function schema (in TOOL_SPECS) plus, for read tools, a
handler(ctx, args) -> str; the handoff tool is intercepted by the loop.
"""

import json
import logging

from agents.chat import domain as d
from agents.chat import db

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
    briefs = {b["id"]: b for b in db.notes_brief(ctx.user_id, source_ids[:4])}
    for nid in source_ids[:4]:
        b = briefs.get(nid)
        if b:
            ctx.cite(nid, _label(b.get("title"), b.get("text")))
    return ans or "No relevant notes found."


def _get_note(ctx: Ctx, args: dict) -> str:
    nid = args.get("note_id")
    n = db.get_note_for_user(ctx.user_id, int(nid)) if nid is not None else None
    if not n:
        return "Error: note not found."
    ctx.cite(n["id"], _label(n.get("title"), n.get("text")))
    return _json({"id": n["id"], "title": n["title"], "path": n["path"],
                  "tags": n["tags"], "text": n["text"]})


def _neighbors(ctx: Ctx, args: dict) -> str:
    nid = args.get("note_id")
    if nid is None:
        return "Error: note_id is required."
    rows = db.links_of_for_user(ctx.user_id, int(nid))
    out = [{"id": r[0], "title": r[1] or "untitled", "direction": r[3]} for r in rows]
    return _json(out) if out else "No linked notes."


def _list_reminders(ctx: Ctx, args: dict) -> str:
    rows = db.upcoming_reminders(ctx.user_id)
    out = [{"id": r[0], "remind_at": r[1], "text": r[2], "status": r[3]} for r in rows]
    return _json(out) if out else "No upcoming reminders."


def _list_paths(ctx: Ctx, args: dict) -> str:
    return _json(d.known_paths(ctx.user_id))


HANDLERS = {
    "search_notes": _search_notes,
    "get_note": _get_note,
    "neighbors": _neighbors,
    "list_reminders": _list_reminders,
    "list_paths": _list_paths,
}

# Handoff tools have no local handler. The loop routes each to its owning agent
# and pauses for the user's confirmation.
ENRICH_HANDOFF_TOOLS = {"perform_action"}
REMINDER_HANDOFF_TOOLS = {"set_reminder"}
HANDOFF_TOOLS = ENRICH_HANDOFF_TOOLS | REMINDER_HANDOFF_TOOLS


def execute_tool(ctx: Ctx, name: str, args: dict) -> str:
    fn = HANDLERS.get(name)
    if not fn:
        return "Error: unknown tool %s." % name
    logger.info("chat tool %s user=%s args=%s", name, ctx.user_id, args)
    try:
        return fn(ctx, args or {})
    except Exception as exc:
        logger.exception("chat tool %s failed", name)
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
    _fn("perform_action",
        "Use this when the user asks you to DO something rather than answer a "
        "question — create a note, move a note to a folder, or classify/enrich a "
        "note. Do not use it for reminders. Pass the user's request verbatim as "
        "`instruction`. "
        "A specialized action agent proposes the exact change and the user confirms "
        "it before anything happens.",
        {"instruction": {"type": "string", "description": "The user's request, verbatim."}},
        ["instruction"]),
    _fn("set_reminder",
        "Use this when the user asks to set or schedule a reminder. Pass the full "
        "request verbatim, including what to remember and every date/time detail. "
        "The reminder agent resolves the time and proposes it for confirmation.",
        {"instruction": {"type": "string", "description": "The reminder request, verbatim."}},
        ["instruction"]),
]
