"""Human approval and idempotent execution node for Enrich."""

from langgraph.types import interrupt

from common import helper
from agents.contracts import ToolResult
from tools import enrich as tools
from agents.enrich.state import EnrichState, context_from_state, context_to_dict
from agents.runtime.execute_tool import execute_tool
from agents.runtime import execution_ledger


def _tool_text(result) -> str:
    if isinstance(result, ToolResult):
        return helper.json_text(result.data)

    return str(result)


def run(state: EnrichState) -> dict:
    pending = state["pending"]
    approved = bool(interrupt({
        "action_id": pending["action_id"], "agent": "enrich",
        "action": state["action"], "summary": pending.get("summary"),
    }))
    ctx = context_from_state(state)
    context = context_to_dict(ctx)
    if approved:
        action = {"name": pending["name"], "args": pending["args"],
                  "summary": pending["summary"]}
        result = execution_ledger.execute_once(
            pending["action_id"], ctx.user_id, "enrich", action,
            lambda: _tool_text(execute_tool(
                tools.TOOLS,
                context,
                pending["name"],
                pending["args"],
                "enrich",
            )),
        )
    else:
        result = "The user declined this action; do not perform it. Acknowledge and continue."
    message = {"role": "tool", "tool_call_id": pending["tool_call_id"],
               "content": str(result)}
    return {"messages": [*state["messages"], message], "pending": None,
            "action": None, "completed_action_id": pending["action_id"],
            "status": "answer"}
