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


def _map(thread_id, result):
    payload_key = "reply" if result["status"] == "answer" else "action"

    return {
        "thread_id": thread_id,
        "status": result["status"],
        "citations": result.get("citations") or [],
        payload_key: result[payload_key],
    }


def _latest_or_projection(state_snapshot, messages, pending):
    """Use the checkpoint as truth, falling back to pre-checkpointer thread data."""
    if state_snapshot.values:
        return (
            list(state_snapshot.values.get("messages") or []),
            state_snapshot.values.get("pending"))

    return list(messages), pending


def _with_action_id(thread_id, pending) -> dict:
    """The pending action plus a stable action id, so a retry reuses the same one."""
    fingerprint = json.dumps({
        "thread_id": thread_id,
        "tool_call_id": pending.get("tool_call_id"),
        "agent": pending.get("agent", "enrich"),
        "action": pending.get("action"),
    }, sort_keys=True, separators=(",", ":"), default=str)

    return {**pending, "action_id": str(uuid.uuid5(uuid.NAMESPACE_URL, fingerprint))}


def evaluate_turn(user_id: int, messages: list[dict], now, tz, locale) -> dict:
    """Run an isolated turn for evaluation without creating a saved thread."""
    ctx = _ctx(user_id, now, tz, locale)
    graph = loop.build_graph(InMemorySaver())
    graph_config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    return loop.invoke(
        graph, 
        graph_config, 
        initial_state(ctx, with_system(list(messages), now, tz)))


def entry_point(user_id, message, thread_id, now, tz, locale):
    """Run one user message. Returns {thread_id, status, reply|action, citations}."""

    thread = db.get_thread(user_id, thread_id) if thread_id is not None else None

    if thread is None:
        thread_id, messages, pending = db.create_thread(user_id), [], None
    else:
        thread_id, messages, pending = (
            thread["id"],
            list(thread["messages"]),
            thread.get("pending"),
        )

    with checkpoint.session(loop.build_graph, "chat", thread_id) as (graph, graph_config):
        state_snapshot = graph.get_state(graph_config)
        messages, pending = _latest_or_projection(state_snapshot, messages, pending)

        if state_snapshot.values and checkpoint.has_interrupts(state_snapshot.tasks):
            result = dict(state_snapshot.values)
        else:
            if state_snapshot.values and state_snapshot.next:
                # This request is recovering an unfinished prior turn. Return
                # that turn's result instead of appending the retried message.
                recovered = loop.retry(graph, graph_config)

                db.save_thread(thread_id, recovered.get("messages") or [], recovered.get("pending"))

                return _map(thread_id, recovered)

            if pending:
                if not pending.get("action_id"):
                    pending = _with_action_id(thread_id, pending)
                    db.save_thread(thread_id, messages, pending)
            else:
                messages = with_system(messages, now, tz)
                messages.append({"role": "user", "content": message})

            references = []

            if state_snapshot.values:
                references = state_snapshot.values.get("reference_notes") or []

            result = loop.invoke(
                graph,
                graph_config,
                initial_state(
                    Ctx(user_id, now, tz=tz, locale=locale),
                    messages,
                    pending,
                    references))
            db.save_thread(thread_id, result.get("messages") or [], result.get("pending"))

        return _map(thread_id, result)


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
    thread = db.get_thread(user_id, thread_id)

    if thread is None:
        return {
          "thread_id": thread_id,
          "status": "answer",
          "reply": "There's nothing to confirm.",
          "citations": []}

    ctx = _ctx(user_id, now, tz, locale)
    with checkpoint.session(loop.build_graph, "chat", thread_id) as (graph, graph_config):
        state_snapshot = graph.get_state(graph_config)

        if not state_snapshot.values:
            if not thread.get("pending"):
                return {
                  "thread_id": thread_id,
                  "status": "answer",
                  "reply": "There's nothing to confirm.",
                  "citations": []}

            messages = list(thread["messages"])
            pending = thread["pending"]

            if not pending.get("action_id"):
                pending = _with_action_id(thread_id, pending)
                db.save_thread(thread_id, messages, pending)

            loop.invoke(
                graph,
                graph_config,
                initial_state(ctx, messages, pending),
            )
            state_snapshot = graph.get_state(graph_config)

        if checkpoint.has_interrupts(state_snapshot.tasks):
            result = loop.resume(graph, graph_config, decision)
        elif state_snapshot.next:
            # The approval was already consumed and a later node failed. Resume
            # that exact node; the action ledger also protects its side effect.
            result = loop.retry(graph, graph_config)
        elif state_snapshot.values.get("completed_action_id"):
            # Confirmation response may have been lost after the graph finished.
            # Return the checkpointed answer without executing anything again.
            result = dict(state_snapshot.values)
        else:
            return {
              "thread_id": thread_id, 
              "status": "answer",
              "reply": "There's nothing to confirm.", 
              "citations": []}

        db.save_thread(thread_id, result.get("messages") or [], result.get("pending"))

        return _map(thread_id, result)
