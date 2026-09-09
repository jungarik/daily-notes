"""Approve node: human approval, then idempotent execution via the specialist.

Interrupts the graph with the staged action and resumes on the user's decision.
Execution — selecting the owning specialist, applying a select action's chosen
note ids, and running it exactly once — belongs to the handoff broker; this node
only shapes the outcome back into graph state. The only public entry point is
`run`.
"""

from langgraph.types import interrupt

from agents.bootstrap import broker
from agents.conversation.state import ChatState, context_from_state, context_update
from agents.runtime import handoff_broker
from agents.runtime.handoff_broker import DECLINED


def _decision(raw) -> tuple:
    """Split a resume value into (approved, selection). The client may send a
    bare bool, or a dict carrying a selection of note ids for a select action."""
    if isinstance(raw, dict):
        return bool(raw.get("approve")), raw.get("selection")

    return bool(raw), None


def run(state: ChatState) -> dict:
    pending = state.get("pending")

    if not pending:
        return {
            "status": "answer",
            "reply": "There is no action to confirm.",
            "action": None,
            "tool_call": None,
        }

    approved, selection = _decision(interrupt({
        "action_id": pending["action_id"],
        "agent": pending.get("agent", "enrich"),
        "action": pending["action"],
        "summary": pending.get("summary"),
    }))
    ctx = context_from_state(state)

    if approved:
        result = handoff_broker.execute(pending, broker.registry, broker.ledger, ctx, selection)
    else:
        result = DECLINED

    message = {
        "role": "tool",
        "tool_call_id": pending["tool_call_id"],
        "content": str(result),
    }

    messages = state.get("messages") or []

    return {
        "messages": [*messages, message],
        "pending": None,
        "action": None,
        "completed_action_id": pending["action_id"],
        "status": "answer",
        **context_update(ctx), #Flatten context into the top-level dictionary
    }
