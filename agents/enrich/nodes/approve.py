"""Approve node: human approval, then idempotent execution for Enrich.

Interrupts with the staged action, resumes on the user's decision, and executes
it exactly once through the enrichment tools (or records a decline). `run` owns
the interrupt and the execution; the helpers below are pure. Single public `run`.
"""

from langgraph.types import interrupt

from common import helper
from agents.contracts import ToolResult
from agents.enrich.state import EnrichState, context_from_state, context_to_dict
from tools import enrich as tools
from agents.runtime.execute_tool import execute_tool
from agents.runtime import execution_ledger

DECLINED = ("The user declined this action; do not perform it. "
            "Acknowledge and continue.")


def _result_text(result) -> str:
    if isinstance(result, ToolResult):
        return helper.json_text(result.data)

    return str(result)


def _action(pending: dict) -> dict:
    return {
        "name": pending["name"],
        "args": pending["args"],
        "summary": pending["summary"],
    }


def _interrupt_payload(pending: dict, action: dict | None) -> dict:
    return {
        "action_id": pending["action_id"],
        "agent": "enrich",
        "action": action,
        "summary": pending.get("summary"),
    }


def _completed(messages: list[dict], pending: dict, result: str) -> dict:
    return {
        "messages": [*messages, {
            "role": "tool",
            "tool_call_id": pending["tool_call_id"],
            "content": str(result),
        }],
        "pending": None,
        "action": None,
        "completed_action_id": pending["action_id"],
        "status": "answer",
    }


def run(state: EnrichState) -> dict:
    pending = state["pending"]
    approved = bool(interrupt(_interrupt_payload(pending, state.get("action"))))
    ctx = context_from_state(state)
    action = _action(pending)

    if not approved:
        return _completed(state.get("messages") or [], pending, DECLINED)

    context = context_to_dict(ctx)
    result = execution_ledger.execute_once(
        pending["action_id"],
        ctx.user_id,
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

    return _completed(state.get("messages") or [], pending, result)
