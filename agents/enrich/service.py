"""Enrichment/action agent orchestration: thread state + turn/confirm entry points.

Loads/creates a thread, runs the loop, persists the running message list and any
paused write, and shapes the response. Client-agnostic — the caller passes the
user's clock/locale. A write pauses the loop; `confirm` resumes it (executing or
declining), then continues to the reply. Reserved for the web-app capture path.
"""

import json
import logging
import uuid

from agents.enrich.tools import (
    Ctx, TOOL_SPECS, execute_tool,
)
from agents import checkpoint
from agents import handoff
from agents.enrich import loop
from agents.enrich import db

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are the note-processing assistant for the user's personal notes app (a "
    "Zettelkasten-style vault). You TAKE ACTIONS on their notes: create notes, "
    "move notes to a vault path, "
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


def _project(thread_id, result):
    db.save_thread(thread_id, result.get("messages") or [], result.get("pending"))


def _latest_or_projection(graph, graph_config, messages, pending):
    snapshot = graph.get_state(graph_config)
    if snapshot.values:
        return snapshot, list(snapshot.values.get("messages") or []), snapshot.values.get("pending")
    return snapshot, list(messages), pending


def _checkpoint_action_id(thread_id, messages, pending):
    """Upgrade older pending writes and persist their stable id before execution."""
    if pending.get("action_id"):
        return pending
    pending = dict(pending)
    identity = json.dumps({
        "thread_id": thread_id,
        "tool_call_id": pending.get("tool_call_id"),
        "name": pending.get("name"),
        "args": pending.get("args"),
    }, sort_keys=True, separators=(",", ":"), default=str)
    pending["action_id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, identity))
    db.save_thread(thread_id, messages, pending)
    return pending


def start_turn(user_id, message, thread_id, now, tz, locale):
    """Run one user instruction. Returns {thread_id, status, reply|action}."""
    thread_id, messages, pending = _load(user_id, thread_id)
    ctx = Ctx(user_id, now, tz=tz, locale=locale)
    with checkpoint.session(loop.build_graph, "enrich", thread_id) as (graph, graph_config):
        snapshot, messages, pending = _latest_or_projection(
            graph, graph_config, messages, pending)
        if snapshot.values and checkpoint.is_interrupted(snapshot):
            result = dict(snapshot.values)
        else:
            if snapshot.values and snapshot.next:
                recovered = loop.retry(graph, graph_config)
                _project(thread_id, recovered)
                return _shape(thread_id, recovered)
            if pending:
                pending = _checkpoint_action_id(thread_id, messages, pending)
            else:
                messages = _with_system(messages)
                messages.append({"role": "user", "content": message})
            result = loop.invoke(
                graph, graph_config, loop.initial_state(ctx, messages, pending))
        _project(thread_id, result)
        return _shape(thread_id, result)


def confirm(user_id, thread_id, approve, now, tz, locale):
    """Resume a thread paused on a write: execute (or decline) it and continue."""
    t = db.get_thread(user_id, thread_id)
    if t is None:
        return {"thread_id": thread_id, "status": "answer", "reply": "There's nothing to confirm."}
    ctx = Ctx(user_id, now, tz=tz, locale=locale)
    with checkpoint.session(loop.build_graph, "enrich", thread_id) as (graph, graph_config):
        snapshot = graph.get_state(graph_config)
        if not snapshot.values:
            if not t.get("pending"):
                return {"thread_id": thread_id, "status": "answer",
                        "reply": "There's nothing to confirm."}
            pending = _checkpoint_action_id(thread_id, list(t["messages"]), t["pending"])
            loop.invoke(
                graph, graph_config,
                loop.initial_state(ctx, list(t["messages"]), pending),
            )
            snapshot = graph.get_state(graph_config)
        if checkpoint.is_interrupted(snapshot):
            result = loop.resume(graph, graph_config, bool(approve))
        elif snapshot.next:
            result = loop.retry(graph, graph_config)
        elif snapshot.values.get("completed_action_id"):
            result = dict(snapshot.values)
        else:
            return {"thread_id": thread_id, "status": "answer",
                    "reply": "There's nothing to confirm."}
        _project(thread_id, result)
        return _shape(thread_id, result)


# ----- stateless handoff API (used by the chat agent) ----------------------

def plan_action(user_id: int, request, now, tz, locale) -> dict | None:
    """One-shot: decide the single write action a natural-language instruction
    implies. Returns {name, args, summary} for a write tool, or None if no
    concrete action could be determined. Does not execute anything."""
    contract = handoff.normalize(request, now, tz, locale)
    ctx = Ctx(user_id, now, tz=tz, locale=locale)
    messages = [{
        "role": "system",
        "content": (
            SYSTEM_PROMPT
            + " You are planning from a typed Chat handoff. Use get_note_context "
              "for referenced notes and list_paths/list_tags when those reads are "
              "needed. Do not execute writes. Finish by choosing exactly one write "
              "tool only when its target and arguments are resolved; otherwise answer "
              "without a tool so Chat can ask for clarification. Handoff:\n"
            + json.dumps(contract, ensure_ascii=False, default=str)
        ),
    }, {"role": "user", "content": contract["instruction"]}]
    try:
        return loop.plan_action(ctx, messages, TOOL_SPECS)
    except Exception:
        logger.exception("plan_action failed for user %s", user_id)
        return None


def execute_action(user_id: int, action: dict, now, tz, locale) -> str:
    """Run a planned write action (after the user approved it). Returns the tool's
    result string."""
    ctx = Ctx(user_id, now, tz=tz, locale=locale)
    return execute_tool(ctx, action["name"], action.get("args") or {})
