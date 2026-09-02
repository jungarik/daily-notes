"""Read-tool nodes for Enrich workflows."""

from agents.enrich.state import (
    ActionPlanState,
    EnrichState,
    context_from_state,
    context_to_dict,
)
from common import helper
from agents.contracts import ToolResult
from tools import enrich as tools
from agents.runtime.execute_tool import execute_tool


def _tool_text(result) -> str:
    if isinstance(result, ToolResult):
        return helper.json_text(result.data)

    return str(result)


def _execute(state) -> dict:
    tool_call = state["tool_call"]
    result = _tool_text(execute_tool(
        tools.TOOLS,
        context_to_dict(context_from_state(state)),
        tool_call["name"],
        tool_call["args"],
        "enrich",
    ))
    message = {"role": "tool", "tool_call_id": tool_call["id"],
               "content": str(result)}
    return {"messages": [*state["messages"], message], "tool_call": None}


def run(state: EnrichState) -> dict:
    return _execute(state)


def plan(state: ActionPlanState) -> dict:
    return _execute(state)
