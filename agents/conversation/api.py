"""Public surface for conversation turns and confirmations.

Runs the loop over thread data the caller supplies and returns the raw result;
loading, persisting and response shaping belong to the calling section (see
`api/chat`). Client-agnostic — the API layer passes the caller's clock/locale.

The chat agent answers questions (read tools) and, when the user asks it to DO
something, hands the action to the owning specialist; that write pauses for the
user's confirmation, and `run_confirmation` resumes it through the same
specialist.
"""

import json
import uuid

from langgraph.checkpoint.memory import InMemorySaver

import config
from agents.conversation.state import ConversationContext as Ctx, initial_state
from agents.runtime import checkpoint
from agents.runtime import loop
from agents.conversation.graph import build_graph
from agents.conversation.prompts import with_system


def _decision(approve, selection):
    """The resume value: a bare flag, or a flag plus the note ids the user picked."""
    if selection is None:
        return bool(approve)

    return {
        "approve": bool(approve),
        "selection": selection,
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
    ctx = Ctx(user_id, now, tz=tz, locale=locale)
    graph = build_graph(InMemorySaver())
    graph_config = checkpoint.graph_config("eval", uuid.uuid4(),
                                           config.AGENT_MAX_STEPS)

    return loop.invoke(
        graph,
        graph_config,
        initial_state(ctx, with_system(list(messages), now, tz)))


def run_turn(thread_id, messages, pending, message, user_id, now, tz, locale) -> dict:
    """Drive the graph for one user message over the given thread data and return
    its result. Persistence and response shaping belong to the caller."""
    ctx = Ctx(user_id, now, tz=tz, locale=locale)

    with checkpoint.saver_session() as checkpointer:
        graph = build_graph(checkpointer)
        graph_config = checkpoint.graph_config("chat", thread_id,
                                               config.AGENT_MAX_STEPS)
        state_snapshot = graph.get_state(graph_config)
        messages, pending = _latest_or_projection(state_snapshot, messages, pending)

        if state_snapshot.values and checkpoint.has_interrupts(state_snapshot.tasks):
            return dict(state_snapshot.values)

        if state_snapshot.values and state_snapshot.next:
            # This request is recovering an unfinished prior turn. Return that
            # turn's result instead of appending the retried message.
            return loop.retry(graph, graph_config)

        if pending:
            if not pending.get("action_id"):
                pending = _with_action_id(thread_id, pending)
        else:
            messages = with_system(messages, now, tz)
            messages.append({"role": "user", "content": message})

        return loop.invoke(
            graph,
            graph_config,
            initial_state(
                ctx,
                messages,
                pending,
                (state_snapshot.values or {}).get("reference_notes") or []))


def run_confirmation(thread_id, messages, pending, approve, selection,
                     user_id, now, tz, locale):
    """Resume the paused graph and return its result, or None when the thread has
    no action awaiting a decision. Persistence belongs to the caller."""
    ctx = Ctx(user_id, now, tz=tz, locale=locale)
    decision = _decision(approve, selection)

    with checkpoint.saver_session() as checkpointer:
        graph = build_graph(checkpointer)
        graph_config = checkpoint.graph_config("chat", thread_id,
                                               config.AGENT_MAX_STEPS)
        state_snapshot = graph.get_state(graph_config)

        if not state_snapshot.values:
            if not pending:
                return None

            if not pending.get("action_id"):
                pending = _with_action_id(thread_id, pending)

            loop.invoke(graph, graph_config, initial_state(ctx, messages, pending))
            state_snapshot = graph.get_state(graph_config)

        if checkpoint.has_interrupts(state_snapshot.tasks):
            return loop.resume(graph, graph_config, decision)

        if state_snapshot.next:
            # The approval was already consumed and a later node failed. Resume
            # that exact node; the action ledger also protects its side effect.
            return loop.retry(graph, graph_config)

        if state_snapshot.values.get("completed_action_id"):
            # Confirmation response may have been lost after the graph finished.
            # Return the checkpointed answer without executing anything again.
            return dict(state_snapshot.values)

        return None
