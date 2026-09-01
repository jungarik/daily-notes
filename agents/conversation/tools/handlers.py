"""Execution handlers for read-only Knowledge tools."""

import json
import logging
from datetime import datetime

import config
import i18n
from openai_client import get_client

from agents.conversation.state import ConversationContext
from agents.conversation.tools import db

logger = logging.getLogger(__name__)


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _label(title, text) -> str:
    title = (title or "").strip()
    if title:
        return title
    snippet = " ".join((text or "").split())
    if not snippet:
        return "note"
    return snippet[:40] + "…" if len(snippet) > 40 else snippet


def _embed(text: str) -> str:
    response = get_client().embeddings.create(model=config.EMBED_MODEL, input=text)
    return str(response.data[0].embedding)


def _known_paths(user_id: int) -> list[str]:
    _, raw_language = db.get_user_settings(user_id)
    locale = i18n.normalize(raw_language) or i18n.DEFAULT_LOCALE
    roots = {i18n.t(locale, key) for key in config.ROOT_FOLDERS}
    paths = [name for name, _ in db.list_paths(user_id)]
    paths.extend(name for name in roots if name not in paths)
    return paths


def _search_notes(ctx: ConversationContext, args: dict) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "Error: query is required."
    hits = db.search_chunks(ctx.user_id, _embed(query))
    if not hits:
        return "No relevant notes found."
    ctx.trace["retrieved_chunks"].extend({
        "chunk_id": hit["chunk_id"], "note_id": hit["note_id"],
        "rank": hit["rank"], "similarity": hit["similarity"],
        "content": hit["content"][:1000],
    } for hit in hits)
    source_ids = list(dict.fromkeys(hit["note_id"] for hit in hits))
    briefs = {b["id"]: b for b in db.notes_brief(ctx.user_id, source_ids[:4])}
    for note_id in source_ids[:4]:
        brief = briefs.get(note_id)
        if brief:
            ctx.cite(note_id, _label(brief.get("title"), brief.get("text")))
    evidence = []
    for hit in hits:
        brief = briefs.get(hit["note_id"], {})
        evidence.append({
            "chunk_id": hit["chunk_id"], "note_id": hit["note_id"],
            "title": brief.get("title"), "path": brief.get("path"),
            "content": hit["content"], "rank": hit["rank"],
            "similarity": hit["similarity"], "created_at": hit["created_at"],
            "remind_at": hit.get("remind_at"), "source_type": hit["source_type"],
        })
    return _json({"query": query, "evidence": evidence})


def _get_note(ctx: ConversationContext, args: dict) -> str:
    note_id = args.get("note_id")
    note = db.get_note_for_user(ctx.user_id, int(note_id)) if note_id is not None else None
    if not note:
        return "Error: note not found."
    ctx.cite(note["id"], _label(note.get("title"), note.get("text")))
    return _json({"id": note["id"], "title": note["title"], "path": note["path"],
                  "tags": note["tags"], "text": note["text"]})


def _neighbors(ctx: ConversationContext, args: dict) -> str:
    note_id = args.get("note_id")
    if note_id is None:
        return "Error: note_id is required."
    rows = db.links_of_for_user(ctx.user_id, int(note_id))
    result = [{"id": row[0], "title": row[1] or "untitled", "direction": row[3]}
              for row in rows]
    return _json(result) if result else "No linked notes."


def _list_reminders(ctx: ConversationContext, _args: dict) -> str:
    rows = db.upcoming_reminders(ctx.user_id)
    result = [{"id": row[0], "remind_at": row[1], "text": row[2], "status": row[3]}
              for row in rows]
    return _json(result) if result else "No upcoming reminders."


def _agenda_time(ctx: ConversationContext, raw, field: str):
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be an ISO-8601 date/time")
    if value.tzinfo is None:
        if not hasattr(ctx.tz, "utcoffset"):
            raise ValueError(f"{field} must include a UTC offset")
        value = value.replace(tzinfo=ctx.tz)
    return value


def _list_agenda(ctx: ConversationContext, args: dict) -> str:
    start_at = _agenda_time(ctx, args.get("start_at"), "start_at")
    end_at = _agenda_time(ctx, args.get("end_at"), "end_at")
    if end_at <= start_at:
        return "Error: end_at must be after start_at."
    rows = db.agenda_reminders(ctx.user_id, start_at, end_at)
    for row in rows:
        ctx.cite(row["note_id"], _label(row.get("title"), row.get("text")))
    return _json(rows) if rows else "No reminders in that period."


def _list_paths(ctx: ConversationContext, _args: dict) -> str:
    return _json(_known_paths(ctx.user_id))


HANDLERS = {
    "search_notes": _search_notes, 
    "get_note": _get_note,
    "neighbors": _neighbors, 
    "list_reminders": _list_reminders,
    "list_agenda": _list_agenda,
    "list_paths": _list_paths,
}


def execute_tool(ctx: ConversationContext, name: str, args: dict) -> str:
    handler = HANDLERS.get(name)
    if not handler:
        return "Error: unknown tool %s." % name
    logger.info("knowledge tool %s user=%s args=%s", name, ctx.user_id, args)
    try:
        return handler(ctx, args or {})
    except Exception as exc:
        logger.exception("knowledge tool %s failed", name)
        return "Error running %s: %s" % (name, exc)
