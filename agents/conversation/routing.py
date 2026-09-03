"""Conditional edges for the conversation graph.

A small ReAct loop with a human-approval pause:

    START ─entry──▶ reason | approve
    reason ─after_reason─▶ act | handoff | END
    act ────────────────▶ reason
    handoff ─after_handoff─▶ approve | reason
    approve ─────────────▶ reason
"""

from langgraph.graph import END

from agents.conversation.state import ChatState
from tools.conversation import HANDOFF_TOOLS


def entry(state: ChatState):
    """Resume a paused approval, otherwise start reasoning."""
    return "approve" if state.get("pending") else "reason"


def after_reason(state: ChatState):
    """Run a read tool, hand a write to a specialist, or answer and finish."""
    tool_call = state.get("tool_call")

    if tool_call is None:
        return END

    if tool_call["name"] in HANDOFF_TOOLS:
        return "handoff"

    return "act"


def after_handoff(state: ChatState):
    """A staged action pauses for approval; nothing concrete loops back."""
    return "approve" if state.get("pending") else "reason"
