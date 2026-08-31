"""Chat agent orchestration: thread state + turn/confirm entry points.

Loads/creates a conversation thread, runs the loop, persists the running message
list and any handed-off action awaiting confirmation, and shapes the client
response. Client-agnostic — the API layer passes the caller's clock/locale.

The chat agent answers questions (read tools) and, when the user asks it to DO
something, hands the action to the owning specialist; that write pauses for the
user's confirmation, and `confirm` resumes it through the same specialist.
"""

import logging

from agents.chat.tools import Ctx
from agents.chat.loop import run_loop, resume_action
from agents.chat import db as chat_store

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an assistant embedded in the user's personal notes app (a "
    "Zettelkasten-style vault of their own notes, reminders and links). Answer "
    "questions about what they've captured by USING THE READ TOOLS — never invent "
    "note content. Prefer `search_notes` first, then `get_note`/`neighbors` to dig "
    "in. Cite the notes you used by their title. When the user asks you to DO "
    "something — use `set_reminder` for reminders, and use `perform_action` to "
    "create or move a note or classify/enrich it. Pass the full request; the "
    "appropriate specialized agent will "
    "propose the change and the user confirms it. Be concise."
)


def _ctx(user_id, now, tz, locale):
    return Ctx(user_id, now, tz=tz, locale=locale)


def _load(user_id, thread_id):
    """Return (thread_id, messages, pending) for an existing thread, or a fresh one."""
    if thread_id is not None:
        t = chat_store.get_thread(user_id, thread_id)
        if t is not None:
            return t["id"], list(t["messages"]), t.get("pending")
    return chat_store.create_thread(user_id), [], None


def _with_system(messages):
    if not messages or messages[0].get("role") != "system":
        return [{"role": "system", "content": SYSTEM_PROMPT}] + messages
    return messages


def _shape(thread_id, result, ctx):
    out = {"thread_id": thread_id, "status": result["status"], "citations": ctx.citations}
    if result["status"] == "answer":
        out["reply"] = result["reply"]
    else:
        out["action"] = result["action"]
    return out


def start_turn(user_id, message, thread_id, now, tz, locale):
    """Run one user message. Returns {thread_id, status, reply|action, citations}."""
    thread_id, messages, _ = _load(user_id, thread_id)
    messages = _with_system(messages)
    messages.append({"role": "user", "content": message})
    ctx = _ctx(user_id, now, tz, locale)
    result = run_loop(ctx, messages)
    chat_store.save_thread(thread_id, result["messages"], result.get("pending"))
    return _shape(thread_id, result, ctx)


def confirm(user_id, thread_id, approve, now, tz, locale):
    """Resume a thread paused on a handed-off action: run (or decline) it via the
    owning specialist and continue to a final reply."""
    t = chat_store.get_thread(user_id, thread_id)
    if t is None or not t.get("pending"):
        return {"thread_id": thread_id, "status": "answer",
                "reply": "There's nothing to confirm.", "citations": []}
    ctx = _ctx(user_id, now, tz, locale)
    result = resume_action(ctx, list(t["messages"]), t["pending"], bool(approve))
    chat_store.save_thread(thread_id, result["messages"], result.get("pending"))
    return _shape(thread_id, result, ctx)
