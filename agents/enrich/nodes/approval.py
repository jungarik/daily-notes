"""Human approval and idempotent execution node for Enrich."""

from langgraph.types import interrupt

from agents.enrich.state import EnrichState, context_from_state
from agents.enrich.tools import execute_tool
from agents.runtime import execution_ledger


def run(state: EnrichState) -> dict:
    pending = state["pending"]
    approved = bool(interrupt({
        "action_id": pending["action_id"], "agent": "enrich",
        "action": state["action"], "summary": pending.get("summary"),
    }))
    ctx = context_from_state(state)
    if approved:
        action = {"name": pending["name"], "args": pending["args"],
                  "summary": pending["summary"]}
        result = execution_ledger.execute_once(
            pending["action_id"], ctx.user_id, "enrich", action,
            lambda: execute_tool(ctx, pending["name"], pending["args"]),
        )
    else:
        result = "The user declined this action; do not perform it. Acknowledge and continue."
    message = {"role": "tool", "tool_call_id": pending["tool_call_id"],
               "content": str(result)}
    return {"messages": [*state["messages"], message], "pending": None,
            "action": None, "completed_action_id": pending["action_id"],
            "status": "answer"}
