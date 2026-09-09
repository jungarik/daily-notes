"""Handoff node: route a write/reminder request to its owning specialist.

The broker owns which specialist serves the tool, the typed contract it is given
and the pending record it produces; this node only shapes that into graph state
— staging the action for approval, or returning a tool message when nothing
concrete came back. The only public entry point is `run`.
"""

from agents.bootstrap import broker
from agents.runtime import handoff_broker
from agents.conversation.state import (
    ChatState,
    context_from_state,
    context_update,
    merge_reference_notes,
)


def _no_action(state: ChatState, ctx, call: dict, content: str) -> dict:
    message = {
        "role": "tool",
        "tool_call_id": call["id"],
        "content": content,
    }

    return {
        "messages": [*(state.get("messages") or []), message],
        "tool_call": None,
        "action": None,
        **context_update(ctx),
    }


def run(state: ChatState) -> dict:
    tool_call = state.get("tool_call") or {}
    ctx = context_from_state(state)
    reference_notes = merge_reference_notes(
        state.get("reference_notes") or [],
        ctx.citations)
    plan = handoff_broker.plan(
        broker.route(tool_call["name"]),
        broker.registry,
        state.get("messages") or [],
        tool_call["args"],
        reference_notes,
        ctx)
    ctx.record_tool(
        tool_call["name"],
        tool_call["args"],
        plan.action)
    ctx.record_route(plan.route.mode)

    if not plan.planned:
        return _no_action(state, ctx, tool_call, plan.tool_message)

    return {
        "status": "confirm",
        "action": plan.action,
        "pending": handoff_broker.pending(tool_call["id"], plan),
        "tool_call": None,
        **context_update(ctx),
    }
