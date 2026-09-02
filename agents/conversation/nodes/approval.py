"""Human approval and idempotent execution node."""

from langgraph.types import interrupt

from agents.bootstrap import registry
from agents.conversation.state import ChatState, context_from_state, context_update
from agents.runtime import execution_ledger


def run(state: ChatState) -> dict:
    pending = state.get("pending")

    if not pending:
        return {
            "status": "answer",
            "reply": "There is no action to confirm.",
            "action": None,
            "tool_call": None,
        }

    approved = bool(interrupt({
        "action_id": pending["action_id"],
        "agent": pending.get("agent", "enrich"),
        "action": pending["action"],
        "summary": pending.get("summary"),
    }))
    ctx = context_from_state(state)

    if approved:
        agent_name = "enrich"
        service = registry.get("enrich")
        result = execution_ledger.execute_once(
            pending["action_id"],
            ctx.user_id,
            agent_name,
            pending["action"],
            lambda: service.execute_action(
                ctx.user_id,
                pending["action"],
                ctx.now,
                ctx.tz,
                ctx.locale,
            ),
        )
    else:
        result = "The user declined this action; do not perform it. Acknowledge and continue."

    message = {
        "role": "tool",
        "tool_call_id": pending["tool_call_id"],
        "content": str(result),
    }

    return {
        "messages": [*state["messages"], message],
        "pending": None,
        "action": None,
        "completed_action_id": pending["action_id"],
        "status": "answer",
        **context_update(ctx),
    }
