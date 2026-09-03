"""Handoff node: route a write/reminder request to its owning specialist.

The tool name maps to a specialist mode via `HANDOFF_SPECIALIST`, so adding a
capability is a map entry plus a tool spec — never a new node. The specialist
proposes a concrete action; this node stages it as `pending` for approval, or
returns a tool message when nothing concrete could be determined. The only
public entry point is `run`.
"""

import logging
import uuid

from agents.bootstrap import registry
from agents.contracts import handoff
from agents.conversation.state import (
    ChatState,
    context_from_state,
    context_update,
    merge_references,
)
from tools.conversation import HANDOFF_SPECIALIST

logger = logging.getLogger(__name__)


def _no_action(state: ChatState, ctx, call: dict) -> dict:
    message = {
        "role": "tool",
        "tool_call_id": call["id"],
        "content": "No concrete action could be determined.",
    }

    return {
        "messages": [*state["messages"], message],
        "tool_call": None,
        "action": None,
        **context_update(ctx),
    }


def _plan(state: ChatState, mode: str) -> dict:
    tool_call = state["tool_call"]
    ctx = context_from_state(state)
    references = merge_references(state.get("reference_notes") or [], ctx.citations)
    contract = handoff.build(
        state["messages"],
        tool_call["args"],
        references,
        ctx,
    )
    contract["resolved_entities"]["specialist_mode"] = mode
    action = registry.get("enrich").plan_action(
        ctx.user_id,
        contract,
        ctx.now,
        ctx.tz,
        ctx.locale,
    )
    ctx.record_tool(tool_call["name"], tool_call["args"], action)
    ctx.record_route(mode)

    if not action:
        return _no_action(state, ctx, tool_call)

    pending = {
        "action_id": str(uuid.uuid4()),
        "tool_call_id": tool_call["id"],
        "agent": "enrich",
        "action": action,
        "summary": action["summary"],
        "handoff": contract,
    }
    logger.info(
        "chat handing off to %s: %s user=%s",
        mode,
        action["name"],
        ctx.user_id,
    )

    return {
        "status": "confirm",
        "action": action,
        "pending": pending,
        "tool_call": None,
        **context_update(ctx),
    }


def run(state: ChatState) -> dict:
    tool_call = state.get("tool_call") or {}
    mode = HANDOFF_SPECIALIST.get(tool_call.get("name"), "enrich")

    return _plan(state, mode)
