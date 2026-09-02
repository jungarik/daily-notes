"""Specialist handoff nodes for the conversation graph."""

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

logger = logging.getLogger(__name__)


def handoff_to(state: ChatState, specialist_mode: str) -> dict:
    call = state["tool_call"]
    ctx = context_from_state(state)
    references = merge_references(state.get("reference_notes") or [], ctx.citations)
    contract = handoff.build(
        state["messages"],
        call["args"],
        references,
        ctx,
    )
    contract["resolved_entities"]["specialist_mode"] = specialist_mode
    action = registry.get("enrich").plan_action(
        ctx.user_id,
        contract,
        ctx.now,
        ctx.tz,
        ctx.locale,
    )
    ctx.record_tool(call["name"], call["args"], action)
    ctx.record_route(specialist_mode)

    if not action:
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

    pending = {
        "action_id": str(uuid.uuid4()),
        "tool_call_id": call["id"],
        "agent": "enrich",
        "action": action,
        "summary": action["summary"],
        "handoff": contract,
    }
    logger.info(
        "chat handing off to %s: %s user=%s",
        specialist_mode,
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


def enrich(state: ChatState) -> dict:
    return handoff_to(state, "enrich")


def reminder(state: ChatState) -> dict:
    return handoff_to(state, "reminder")
