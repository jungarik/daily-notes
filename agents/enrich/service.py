"""Enrichment/action agent orchestration: thread state + turn/confirm entry points.

Loads/creates a thread, runs the loop, persists the running message list and any
paused write, and shapes the response. Client-agnostic — the caller passes the
user's clock/locale. A write pauses the loop; `confirm` resumes it (executing or
declining), then continues to the reply. Reserved for the web-app capture path.
"""

import json
import logging

import config
import openai_client
from agents.enrich.tools import (
    Ctx, TOOL_SPECS, WRITE_TOOLS, execute_tool, summarize_write,
)
from agents.enrich.loop import run_loop, resume_write
from agents.enrich import db

logger = logging.getLogger(__name__)

# The write tools' function schemas, for the one-shot handoff planner.
_WRITE_SPECS = [s for s in TOOL_SPECS if s["function"]["name"] in WRITE_TOOLS]

SYSTEM_PROMPT = (
    "You are the note-processing assistant for the user's personal notes app (a "
    "Zettelkasten-style vault). You TAKE ACTIONS on their notes: create notes, "
    "create reminders from time-bearing instructions, move notes to a vault path, "
    "and classify/enrich a note's metadata. Use list_paths/list_tags to stay "
    "consistent with the user's existing vault. Every action is confirmed with the "
    "user before it runs — do not claim something is done until it is. Be concise."
)


def _load(user_id, thread_id):
    """Return (thread_id, messages, pending) for an existing thread, or a fresh one."""
    if thread_id is not None:
        t = db.get_thread(user_id, thread_id)
        if t is not None:
            return t["id"], list(t["messages"]), t.get("pending")
    return db.create_thread(user_id), [], None


def _with_system(messages):
    if not messages or messages[0].get("role") != "system":
        return [{"role": "system", "content": SYSTEM_PROMPT}] + messages
    return messages


def _shape(thread_id, result):
    out = {"thread_id": thread_id, "status": result["status"]}
    if result["status"] == "answer":
        out["reply"] = result["reply"]
    else:
        out["action"] = result["action"]
    return out


def start_turn(user_id, message, thread_id, now, tz, locale):
    """Run one user instruction. Returns {thread_id, status, reply|action}."""
    thread_id, messages, _ = _load(user_id, thread_id)
    messages = _with_system(messages)
    messages.append({"role": "user", "content": message})
    ctx = Ctx(user_id, now, tz=tz, locale=locale)
    result = run_loop(ctx, messages)
    db.save_thread(thread_id, result["messages"], result.get("pending"))
    return _shape(thread_id, result)


def confirm(user_id, thread_id, approve, now, tz, locale):
    """Resume a thread paused on a write: execute (or decline) it and continue."""
    t = db.get_thread(user_id, thread_id)
    if t is None or not t.get("pending"):
        return {"thread_id": thread_id, "status": "answer", "reply": "There's nothing to confirm."}
    ctx = Ctx(user_id, now, tz=tz, locale=locale)
    result = resume_write(ctx, list(t["messages"]), t["pending"], bool(approve))
    db.save_thread(thread_id, result["messages"], result.get("pending"))
    return _shape(thread_id, result)


# ----- stateless handoff API (used by the chat agent) ----------------------

def plan_action(user_id: int, instruction: str, now, tz, locale) -> dict | None:
    """One-shot: decide the single write action a natural-language instruction
    implies. Returns {name, args, summary} for a write tool, or None if no
    concrete action could be determined. Does not execute anything."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + " Choose exactly one action "
         "tool that fulfils the user's request; do not answer in prose."},
        {"role": "user", "content": instruction},
    ]
    try:
        resp = openai_client.get_client().chat.completions.create(
            model=config.ENRICH_AGENT_MODEL, messages=messages, temperature=0,
            tools=_WRITE_SPECS, tool_choice="auto", parallel_tool_calls=False)
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return None
        tc = msg.tool_calls[0]
        name = tc.function.name
        if name not in WRITE_TOOLS:
            return None
        try:
            args = json.loads(tc.function.arguments or "{}")
        except Exception:
            args = {}
        return {"name": name, "args": args, "summary": summarize_write(name, args)}
    except Exception:
        logger.exception("plan_action failed for user %s", user_id)
        return None


def execute_action(user_id: int, action: dict, now, tz, locale) -> str:
    """Run a planned write action (after the user approved it). Returns the tool's
    result string."""
    ctx = Ctx(user_id, now, tz=tz, locale=locale)
    return execute_tool(ctx, action["name"], action.get("args") or {})
