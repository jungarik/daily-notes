"""Act node: execute one Enrich read tool, then loop back.

Shared by the interactive graph and the action-plan graph (identical read
execution). Single public `run`.
"""

from common import helper
from agents.contracts import ToolResult
from agents.enrich.state import context_from_state, context_to_dict
from tools import enrich as tools
from agents.runtime.execute_tool import execute_tool


def _result_text(result) -> str:
    if isinstance(result, ToolResult):
        return helper.json_text(result.data)

    return str(result)


def run(state) -> dict:
    tool_call = state["tool_call"]
    result = _result_text(execute_tool(
        tools.TOOLS,
        context_to_dict(context_from_state(state)),
        tool_call["name"],
        tool_call["args"],
        "enrich",
    ))
    message = {
        "role": "tool",
        "tool_call_id": tool_call["id"],
        "content": str(result),
    }

    return {
        "messages": [*state["messages"], message],
        "tool_call": None,
    }
