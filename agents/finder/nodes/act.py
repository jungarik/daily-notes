"""Act node: execute one read tool the model chose, then loop back to reason.

Owner-scoped reads only (search, note lookups, agenda, reminder detection). It
records citations and references onto the turn context and never mutates data.
The only public entry point is `run`.
"""

from agents.contracts import ToolResult
from agents.finder.state import (
    FinderState,
    apply_tool_result,
    context_from_state,
    context_update,
    merge_reference_notes,
    tool_context,
)
from agents.runtime.execute_tool import execute_tool
from common import helper
from tools import conversation as tools


def _render_result(result) -> str:
    if isinstance(result, ToolResult):
        return helper.json_text(result.data)

    return str(result)


def run(state: FinderState) -> dict:
    tool_call = state.get("tool_call") or {}
    ctx = context_from_state(state)
    result = execute_tool(
        tools.TOOLS,
        tool_context(ctx),
        tool_call["name"],
        tool_call["args"],
        "finder",
    )

    if isinstance(result, ToolResult):
        apply_tool_result(ctx, result)

    text = _render_result(result)
    ctx.record_tool(tool_call["name"], tool_call["args"], text)
    ctx.record_route("rag" if tool_call["name"] == "search_notes" else "tool")
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
            ctx.citations,
        ),
        **context_update(ctx),
    }
