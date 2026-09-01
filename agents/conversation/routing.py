"""Conditional routing decisions for the conversation graph."""

from langgraph.graph import END

import config
from agents.conversation.state import ChatState
from agents.conversation.tools import ENRICH_HANDOFF_TOOLS, REMINDER_HANDOFF_TOOLS


def route_model(state: ChatState):
    call = state.get("tool_call")
    if call is None:
        return END
    if call["name"] in REMINDER_HANDOFF_TOOLS:
        return "reminder_agent"
    if call["name"] in ENRICH_HANDOFF_TOOLS:
        return "enrich_agent"
    return "read_tool"


def route_after_read(state: ChatState):
    return "final" if state.get("steps", 0) >= config.AGENT_MAX_STEPS else "model"


def entry_route(state: ChatState):
    return "approval" if state.get("pending") else "model"
