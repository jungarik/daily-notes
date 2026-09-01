"""Knowledge-read node for the conversation graph."""

from agents.conversation.state import (
    ChatState, context_from_state, context_update, merge_references,
)
from agents.conversation.tools.handlers import execute_tool


def run(state: ChatState) -> dict:
    call = state["tool_call"]
    ctx = context_from_state(state)
    result = execute_tool(ctx, call["name"], call["args"])
    ctx.record_tool(call["name"], call["args"], result)
    ctx.record_route("rag" if call["name"] == "search_notes" else "tool")
    message = {"role": "tool", "tool_call_id": call["id"], "content": str(result)}
    return {"messages": [*state["messages"], message], "tool_call": None,
            "reference_notes": merge_references(
                state.get("reference_notes") or [], ctx.citations),
            **context_update(ctx)}
