"""Thin public facade for conversation turns and confirmations.

Loads/creates a conversation thread, runs the loop, persists the running message
list and any handed-off action awaiting confirmation, and shapes the client
response. Client-agnostic — the API layer passes the caller's clock/locale.

The chat agent answers questions (read tools) and, when the user asks it to DO
something, hands the action to the owning specialist; that write pauses for the
user's confirmation, and `confirm` resumes it through the same specialist.
"""

import json
import uuid

from langgraph.checkpoint.memory import InMemorySaver

from agents.conversation.state import ConversationContext as Ctx, initial_state
from agents.runtime import checkpoint
from agents.conversation import graph as loop
from agents.conversation.prompts import with_system
from agents.conversation import db


def _ctx(user_id, now, tz, locale):
    return Ctx(user_id, now, tz=tz, locale=locale)


def _load(user_id, thread_id):
    """Return (thread_id, messages, pending) for an existing thread, or a fresh one."""
    if thread_id is not None:
        t = db.get_thread(user_id, thread_id)
        if t is not None:
            return t["id"], list(t["messages"]), t.get("pending")
    return db.create_thread(user_id), [], None


def _shape(thread_id, result):
    out = {"thread_id": thread_id, "status": result["status"],
           "citations": result.get("citations") or []}
    if result["status"] == "answer":
        out["reply"] = result["reply"]
    else:
        out["action"] = result["action"]
    return out


def _project(thread_id, result):
    db.save_thread(thread_id, result.get("messages") or [], result.get("pending"))


def _latest_or_projection(graph, graph_config, messages, pending):
    """Use the checkpoint as truth, falling back to pre-checkpointer thread data."""
    snapshot = graph.get_state(graph_config)
    if snapshot.values:
        return snapshot, list(snapshot.values.get("messages") or []), snapshot.values.get("pending")
    return snapshot, list(messages), pending


def _checkpoint_action_id(thread_id, messages, pending):
    """Upgrade older pending actions and persist their stable id before execution."""
    if pending.get("action_id"):
        return pending
    pending = dict(pending)
    identity = json.dumps({
        "thread_id": thread_id,
        "tool_call_id": pending.get("tool_call_id"),
        "agent": pending.get("agent", "enrich"),
        "action": pending.get("action"),
    }, sort_keys=True, separators=(",", ":"), default=str)
    pending["action_id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, identity))
    db.save_thread(thread_id, messages, pending)
    return pending


def evaluate_turn(user_id: int, messages: list[dict], now, tz, locale) -> dict:
    """Run an isolated turn for evaluation without creating a saved thread."""
    ctx = _ctx(user_id, now, tz, locale)
    graph = loop.build_graph(InMemorySaver())
    graph_config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    return loop.invoke(
        graph, 
        graph_config, 
        initial_state(ctx, with_system(list(messages), now, tz)))


def start_turn(user_id, message, thread_id, now, tz, locale):
    """Run one user message. Returns {thread_id, status, reply|action, citations}."""
    thread_id, messages, pending = _load(user_id, thread_id)
    ctx = _ctx(
        user_id,
        now,
        tz,
        locale,
    )
    with checkpoint.session(loop.build_graph, "chat", thread_id) as (graph, graph_config):
        snapshot, messages, pending = _latest_or_projection(
            graph,
            graph_config,
            messages,
            pending,
        )
        if snapshot.values and checkpoint.is_interrupted(snapshot):
            result = dict(snapshot.values)
        else:
            if snapshot.values and snapshot.next:
                # This request is recovering an unfinished prior turn. Return
                # that turn's result instead of appending the retried message.
                recovered = loop.retry(graph, graph_config)
                _project(thread_id, recovered)
                return _shape(thread_id, recovered)
            if pending:
                pending = _checkpoint_action_id(thread_id, messages, pending)
            else:
                messages = with_system(messages, now, tz)
                messages.append({"role": "user", "content": message})
            references = []
            if snapshot.values:
                references = snapshot.values.get("reference_notes") or []
            result = loop.invoke(
                graph,
                graph_config,
                initial_state(
                    ctx,
                    messages,
                    pending,
                    references,
                ),
            )
        _project(thread_id, result)

        return _shape(thread_id, result)


def confirm(user_id, thread_id, approve, now, tz, locale, selection=None):
    """Resume a thread paused on a handed-off action: run (or decline) it via the
    owning specialist and continue to a final reply. `selection` carries the note
    ids the user picked for a select action (link_notes)."""
    decision = ({
          "approve": bool(approve),
          "selection": selection
        } if selection is not None
          else bool(approve)
    )
    t = db.get_thread(user_id, thread_id)
    if t is None:
        return {
          "thread_id": thread_id, 
          "status": "answer",
          "reply": "There's nothing to confirm.", 
          "citations": []}

    ctx = _ctx(user_id, now, tz, locale)
    with checkpoint.session(loop.build_graph, "chat", thread_id) as (graph, graph_config):
        snapshot = graph.get_state(graph_config)
        if not snapshot.values:
            if not t.get("pending"):
                return {
                  "thread_id": thread_id, 
                  "status": "answer",
                  "reply": "There's nothing to confirm.",
                  "citations": []}

            pending = _checkpoint_action_id(thread_id, list(t["messages"]), t["pending"])
            loop.invoke(
                graph, 
                graph_config,
                initial_state(ctx, list(t["messages"]), 
                pending),
            )
            snapshot = graph.get_state(graph_config)
        if checkpoint.is_interrupted(snapshot):
            result = loop.resume(graph, graph_config, decision)
        elif snapshot.next:
            # The approval was already consumed and a later node failed. Resume
            # that exact node; the action ledger also protects its side effect.
            result = loop.retry(graph, graph_config)
        elif snapshot.values.get("completed_action_id"):
            # Confirmation response may have been lost after the graph finished.
            # Return the checkpointed answer without executing anything again.
            result = dict(snapshot.values)
        else:
            return {
              "thread_id": thread_id, 
              "status": "answer",
              "reply": "There's nothing to confirm.", 
              "citations": []}

        _project(thread_id, result)
        return _shape(thread_id, result)
