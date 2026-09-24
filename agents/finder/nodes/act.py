"""Act node: execute one read tool the model chose, then loop back to reason.

Owner-scoped reads only (search, note lookups, agenda, reminder detection). It
never mutates data, and it no longer mutates the turn context either: the
citations and trace it gathers are returned in the state patch, like every
other field this node produces. The only public entry point is `run`.
"""

from agents.contracts import ToolResult
from agents.finder.state import (
    FinderState,
    apply_tool_result,
    context_from_state,
    merge_reference_notes,
    record_route,
    record_tool,
    tool_context,
)
from agents.runtime.execute_tool import execute_tool
from common import helper
from tools import finder as tools


def _render_result(result) -> str:
    if isinstance(result, ToolResult):
        return helper.json_text(result.data)

    return str(result)


def run(state: FinderState) -> dict:
    tool_call = state.get("tool_call") or {}
    result = execute_tool(
        tools.TOOLS,
        tool_context(context_from_state(state)),
        tool_call["name"],
        tool_call["args"],
        "finder",
    )
    citations = state.get("citations") or []
    trace = state.get("trace") or {}

    if isinstance(result, ToolResult):
        citations, trace = apply_tool_result(citations, trace, result)

    text = _render_result(result)
    trace = record_tool(trace, tool_call["name"], tool_call["args"], text)
    trace = record_route(trace, "rag" if tool_call["name"] == "search_notes" else "tool")
    message = {
        "role": "tool",
        "tool_call_id": tool_call["id"],
        "content": text,
    }

    return {
        "messages": [*(state.get("messages") or []), message],
        "tool_call": None,
        "reference_notes": merge_reference_notes(
            state.get("reference_notes") or [],
            citations,
        ),
        "citations": citations,
        "trace": trace,
    }
