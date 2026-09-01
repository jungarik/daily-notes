"""Thin public facade for the enrichment specialist.

Loads/creates a thread, runs the loop, persists the running message list and any
paused write, and shapes the response. Client-agnostic — the caller passes the
user's clock/locale. A write pauses the loop; `confirm` resumes it (executing or
declining), then continues to the reply. Reserved for the web-app capture path.
"""

import json
import logging
import uuid

from agents.contracts import CaptureProposal
from agents.enrich.tools import (
    Ctx, TOOL_SPECS, execute_tool,
)
from agents.contracts import handoff
from agents.runtime import checkpoint
from agents.runtime import execution_ledger
from common import embedings
from common import helper
from agents.enrich import graph as loop
from agents.enrich import db
from agents.enrich.graph import METADATA_GRAPH
from agents.enrich.prompts import SYSTEM_PROMPT, planning_messages, with_system
from agents.enrich.state import context_data

logger = logging.getLogger(__name__)

EDITABLE_CAPTURE_FIELDS = {"text", "title", "path", "tags", "type", "priority",
                           "linked_note_ids"}


def _load(user_id, thread_id):
    """Return (thread_id, messages, pending) for an existing thread, or a fresh one."""
    if thread_id is not None:
        t = db.get_thread(user_id, thread_id)
        if t is not None:
            return t["id"], list(t["messages"]), t.get("pending")
    return db.create_thread(user_id), [], None


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
                messages = with_system(messages)
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
    if (contract.get("resolved_entities") or {}).get("specialist_mode") == "reminder":
        notes = []
        for note_id in contract["referenced_note_ids"]:
            note = db.get_note_for_user(user_id, note_id)
            if note:
                note = dict(note)
                note["note_id"] = note.get("id", note_id)
                notes.append(note)
        contract["resolved_entities"]["referenced_notes"] = notes
        result = loop.REMINDER_PLAN_GRAPH.invoke({
            "contract": contract, "now": now, "action": None,
            "reminder_trace": [],
        })
        return result.get("action")
    ctx = Ctx(user_id, now, tz=tz, locale=locale)
    messages = planning_messages(contract)
    try:
        result = loop.ACTION_PLAN_GRAPH.invoke({
            "messages": messages,
            "context": context_data(ctx),
            "tool_specs": TOOL_SPECS,
            "steps": 0,
            "tool_call": None,
            "action": None,
        })
        return result.get("action")
    except Exception:
        logger.exception("plan_action failed for user %s", user_id)
        return None


def execute_action(user_id: int, action: dict, now, tz, locale) -> str:
    """Run a planned write action (after the user approved it). Returns the tool's
    result string."""
    ctx = Ctx(user_id, now, tz=tz, locale=locale)
    return execute_tool(ctx, action["name"], action.get("args") or {})


# ----- standalone fast-capture API (transport adapters call these) --------

def _capture_proposal(args: dict, related_notes: list[dict]) -> CaptureProposal:
    title = args["title"]
    return {
        "action_id": str(uuid.uuid4()),
        "status": "proposed",
        "action": {
            "name": "capture_thought",
            "args": args,
            "summary": f"Capture “{title}” in {args['path']}.",
        },
        "related_notes": [{
            "note_id": item["note_id"],
            "title": item["title"],
            "path": item.get("path"),
            "distance": item["distance"]} for item in related_notes
        ],
    }


def propose_capture(user_id: int, text: str) -> CaptureProposal:
    """Analyze a thought and return an editable preview. Nothing is persisted."""
    text = text.strip()

    if not text:
        raise ValueError("text is required")

    result = METADATA_GRAPH.invoke({
        "user_id": user_id,
        "metadata_text": text,
        "metadata_note_id": None,
        "metadata_trace": [],
    })
    args = {"text": text, **result["metadata"], "linked_note_ids": []}
    related = (result.get("metadata_context") or {}).get("related_notes") or []

    return _capture_proposal(args, related)


def revise_capture(user_id: int, proposal: CaptureProposal,
                   changes: dict) -> CaptureProposal:
    """Apply user edits and return a new proposal with its own action identity."""
    unknown = set(changes) - EDITABLE_CAPTURE_FIELDS
    if unknown:
        raise ValueError("Unsupported capture fields: " + ", ".join(sorted(unknown)))
    if proposal.get("action", {}).get("name") != "capture_thought":
        raise ValueError("Not a capture proposal")
    args = {**proposal["action"]["args"], **changes}
    text = (args.get("text") or "").strip()
    if not text:
        raise ValueError("text is required")
    roots, default_root = helper.localized_root_folders(db.get_language(user_id))
    metadata = helper.normalize(args, text, roots, default_root)
    linked_ids = list(dict.fromkeys(int(value)
                                    for value in args.get("linked_note_ids") or []))
    missing = [note_id for note_id in linked_ids
               if db.get_note_for_user(user_id, note_id) is None]
    if missing:
        raise ValueError("Linked notes were not found for this user: " +
                         ", ".join(str(note_id) for note_id in missing))
    args = {"text": text, **metadata, "linked_note_ids": linked_ids}
    return _capture_proposal(args, list(proposal.get("related_notes") or []))


def _execute_capture(user_id: int, args: dict) -> dict:
    """Validate and persist an approved fast-capture proposal."""
    text = (args.get("text") or "").strip()
    if not text:
        raise ValueError("text is required")
    roots, default_root = helper.localized_root_folders(db.get_language(user_id))
    metadata = helper.normalize({
        "type": args.get("type"),
        "title": args.get("title"),
        "path": args.get("path"),
        "tags": args.get("tags"),
        "priority": args.get("priority"),
    }, text, roots, default_root)
    linked_note_ids = [int(note_id) for note_id in args.get("linked_note_ids") or []]
    return db.save_captured_thought(
        user_id, text, metadata, embedings.build_chunks(text), linked_note_ids)


def confirm_capture(user_id: int, proposal: CaptureProposal) -> dict:
    """Persist an approved proposal once; retries return its recorded result."""
    action = proposal.get("action") or {}
    if action.get("name") != "capture_thought" or not proposal.get("action_id"):
        raise ValueError("Invalid capture proposal")
    args = action.get("args") or {}
    result = execution_ledger.execute_once(
        proposal["action_id"], user_id, "enrich", action,
        lambda: json.dumps(_execute_capture(user_id, args), ensure_ascii=False),
    )
    try:
        data = json.loads(result)
    except (TypeError, json.JSONDecodeError):
        return {"status": "unchanged", "action_id": proposal["action_id"],
                "message": result}
    return {"status": "completed", "action_id": proposal["action_id"], **data}


def cancel_capture(proposal: CaptureProposal) -> dict:
    """Cancel locally. Since proposals do not write, there is nothing to undo."""
    return {"status": "cancelled", "action_id": proposal.get("action_id")}
