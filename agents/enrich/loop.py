"""LangGraph workflows for the enrichment/action agent.

The turn graph has explicit ``EnrichState`` plus model, read-tool, pending-write,
resume-write, and final nodes. Conditional edges enforce that reads may loop but
writes stop for confirmation. ``ACTION_PLAN_GRAPH`` is the small stateless
sub-workflow used when the chat agent hands a write instruction to this agent.

Thread messages and pending writes continue to be persisted by the service in
PostgreSQL; LangGraph is the orchestration layer, not a second state store.
"""

import json
import logging
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

import config
import openai_client
from agents.enrich.tools import Ctx, TOOL_SPECS, WRITE_TOOLS, execute_tool, summarize_write

logger = logging.getLogger(__name__)


class EnrichState(TypedDict, total=False):
    messages: list[dict]
    ctx: Ctx
    steps: int
    tool_call: dict | None
    status: Literal["answer", "confirm"]
    reply: str
    action: dict | None
    pending: dict | None
    resume: bool
    approve: bool


class ActionPlanState(TypedDict, total=False):
    messages: list[dict]
    tool_specs: list[dict]
    action: dict | None


def _assistant_dict(msg) -> dict:
    data = {"role": "assistant", "content": msg.content}
    if msg.tool_calls:
        data["tool_calls"] = [{
            "id": tc.id,
            "type": "function",
            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
        } for tc in msg.tool_calls]
    return data


def _complete(messages, use_tools):
    kwargs = {"model": config.ENRICH_AGENT_MODEL, "messages": messages, "temperature": 0.2}
    if use_tools:
        kwargs.update(tools=TOOL_SPECS, tool_choice="auto", parallel_tool_calls=False)
    return openai_client.get_client().chat.completions.create(**kwargs)


def _parse_tool_call(msg) -> dict | None:
    if not msg.tool_calls:
        return None
    tc = msg.tool_calls[0]  # parallel_tool_calls=False -> at most one
    try:
        args = json.loads(tc.function.arguments or "{}")
    except Exception:
        args = {}
    return {"id": tc.id, "name": tc.function.name, "args": args}


def _model_node(state: EnrichState) -> dict:
    msg = _complete(state["messages"], use_tools=True).choices[0].message
    messages = [*state["messages"], _assistant_dict(msg)]
    call = _parse_tool_call(msg)
    update = {"messages": messages, "steps": state.get("steps", 0) + 1,
              "tool_call": call}
    if call is None:
        update.update(status="answer", reply=msg.content or "", pending=None)
    return update


def _route_model(state: EnrichState):
    call = state.get("tool_call")
    if call is None:
        return END
    if call["name"] in WRITE_TOOLS:
        return "pending_write"
    return "read_tool"


def _read_tool_node(state: EnrichState) -> dict:
    call = state["tool_call"]
    result = execute_tool(state["ctx"], call["name"], call["args"])
    message = {"role": "tool", "tool_call_id": call["id"], "content": str(result)}
    return {"messages": [*state["messages"], message], "tool_call": None}


def _pending_write_node(state: EnrichState) -> dict:
    call = state["tool_call"]
    summary = summarize_write(call["name"], call["args"])
    pending = {"tool_call_id": call["id"], "name": call["name"],
               "args": call["args"], "summary": summary}
    logger.info("enrich agent pausing for confirmation: %s user=%s",
                call["name"], state["ctx"].user_id)
    action = {"name": call["name"], "args": call["args"], "summary": summary}
    return {"status": "confirm", "action": action, "pending": pending,
            "tool_call": None}


def _route_after_read(state: EnrichState):
    if state.get("steps", 0) >= config.ENRICH_AGENT_MAX_STEPS:
        return "final"
    return "model"


def _resume_write_node(state: EnrichState) -> dict:
    pending = state["pending"]
    if state.get("approve"):
        result = execute_tool(state["ctx"], pending["name"], pending["args"])
    else:
        result = "The user declined this action; do not perform it. Acknowledge and continue."
    message = {"role": "tool", "tool_call_id": pending["tool_call_id"],
               "content": str(result)}
    return {"messages": [*state["messages"], message], "pending": None,
            "action": None, "status": "answer"}


def _final_node(state: EnrichState) -> dict:
    msg = _complete(state["messages"], use_tools=False).choices[0].message
    reply = msg.content or "I couldn't finish that in time."
    return {"messages": [*state["messages"], {"role": "assistant", "content": reply}],
            "status": "answer", "reply": reply, "pending": None}


def _entry_route(state: EnrichState):
    return "resume_write" if state.get("resume") else "model"


def _build_enrich_graph():
    builder = StateGraph(EnrichState)
    builder.add_node("model", _model_node)
    builder.add_node("read_tool", _read_tool_node)
    builder.add_node("pending_write", _pending_write_node)
    builder.add_node("resume_write", _resume_write_node)
    builder.add_node("final", _final_node)

    builder.add_conditional_edges(START, _entry_route,
                                  {"model": "model", "resume_write": "resume_write"})
    builder.add_conditional_edges("model", _route_model,
                                  {"read_tool": "read_tool", "pending_write": "pending_write",
                                   END: END})
    builder.add_conditional_edges("read_tool", _route_after_read,
                                  {"model": "model", "final": "final"})
    builder.add_edge("pending_write", END)
    builder.add_edge("resume_write", "model")
    builder.add_edge("final", END)
    return builder.compile()


def _plan_action_node(state: ActionPlanState) -> dict:
    response = openai_client.get_client().chat.completions.create(
        model=config.ENRICH_AGENT_MODEL,
        messages=state["messages"],
        temperature=0,
        tools=state["tool_specs"],
        tool_choice="auto",
        parallel_tool_calls=False,
    )
    msg = response.choices[0].message
    call = _parse_tool_call(msg)
    if call is None or call["name"] not in WRITE_TOOLS:
        return {"action": None}
    return {"action": {"name": call["name"], "args": call["args"],
                       "summary": summarize_write(call["name"], call["args"])}}


def _build_action_plan_graph():
    builder = StateGraph(ActionPlanState)
    builder.add_node("plan_action", _plan_action_node)
    builder.add_edge(START, "plan_action")
    builder.add_edge("plan_action", END)
    return builder.compile()


ENRICH_GRAPH = _build_enrich_graph()
ACTION_PLAN_GRAPH = _build_action_plan_graph()


def _invoke(state: EnrichState) -> dict:
    limit = max(20, config.ENRICH_AGENT_MAX_STEPS * 3 + 5)
    return ENRICH_GRAPH.invoke(state, {"recursion_limit": limit})


def run_loop(ctx, messages: list) -> dict:
    """Run a normal enrich turn through the compiled LangGraph workflow."""
    return _invoke({"ctx": ctx, "messages": list(messages), "steps": 0,
                    "pending": None, "action": None, "resume": False})


def resume_write(ctx, messages: list, pending: dict, approve: bool) -> dict:
    """Resume a persisted pending write through the graph's confirmation node."""
    return _invoke({"ctx": ctx, "messages": list(messages), "steps": 0,
                    "pending": pending, "action": None, "resume": True,
                    "approve": bool(approve)})


def plan_action(messages: list[dict], tool_specs: list[dict]) -> dict | None:
    """Run the stateless handoff planning sub-workflow and return its action."""
    result = ACTION_PLAN_GRAPH.invoke({"messages": messages, "tool_specs": tool_specs,
                                       "action": None})
    return result.get("action")
