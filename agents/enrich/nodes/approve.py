"""Approve node: human approval, then idempotent execution for Enrich.

Interrupts with the staged action, resumes on the user's decision, and executes
it exactly once through the enrichment tools (or records a decline). Single
public `run`.
"""

from langgraph.types import interrupt

from common import helper
from agents.contracts import ToolResult
from agents.enrich.state import EnrichState, context_from_state, context_to_dict
from tools import enrich as tools
from agents.runtime.execute_tool import execute_tool
from agents.runtime import execution_ledger


def _result_text(result) -> str:
    if isinstance(result, ToolResult):
        return helper.json_text(result.data)

    return str(result)


def _execute(pending: dict, context: dict, user_id: int) -> str:
    action = {
        "name": pending["name"],
        "args": pending["args"],
        "summary": pending["summary"],
    }

    return execution_ledger.execute_once(
        pending["action_id"],
        user_id,
        "enrich",
        action,
        lambda: _result_text(execute_tool(
            tools.TOOLS,
            context,
            pending["name"],
            pending["args"],
            "enrich",
        )),
    )


def run(state: EnrichState) -> dict:
    pending = state["pending"]
    approved = bool(interrupt({
        "action_id": pending["action_id"],
        "agent": "enrich",
        "action": state["action"],
        "summary": pending.get("summary"),
    }))
    ctx = context_from_state(state)

    if approved:
        result = _execute(pending, context_to_dict(ctx), ctx.user_id)
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
    }
