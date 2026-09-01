"""Read-tool nodes for Enrich workflows."""

from agents.enrich.state import ActionPlanState, EnrichState, context_from_state
from agents.enrich.tools import execute_tool


def _execute(state) -> dict:
    call = state["tool_call"]
    result = execute_tool(context_from_state(state), call["name"], call["args"])
    message = {"role": "tool", "tool_call_id": call["id"],
               "content": str(result)}
    return {"messages": [*state["messages"], message], "tool_call": None}


def run(state: EnrichState) -> dict:
    return _execute(state)


def plan(state: ActionPlanState) -> dict:
    return _execute(state)
