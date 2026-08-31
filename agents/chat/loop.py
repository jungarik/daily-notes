"""LangGraph workflow for the read-only chat agent and its enrich handoff.

State
-----
``ChatState`` carries the provider message history, per-turn tool context,
current tool call, step budget, pending confirmation, and terminal response.

Nodes
-----
``model`` plans the next step, ``read_tool`` executes a user-scoped read,
``enrich_agent`` and ``reminder_agent`` hand writes to their specialists,
``resume_action`` applies the user's confirmation, and ``final`` produces a
tool-free fallback.

Edges
-----
START routes a normal turn to ``model`` and a confirmation to
``resume_action``. Model output conditionally routes to a read tool, the enrich
agent, or END. Tool/handoff nodes loop to ``model`` while budget remains, else
route to ``final``. Confirmation resumes at ``model`` after its tool result is
recorded.

PostgreSQL remains the durable thread/checkpoint store at the service boundary;
the graph owns orchestration only, so there is one source of persisted truth.
"""

import json
import logging
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

import config
import openai_client
from agents.chat.tools import (
    Ctx, ENRICH_HANDOFF_TOOLS, REMINDER_HANDOFF_TOOLS, TOOL_SPECS, execute_tool,
)
from agents.enrich import service as enrich_service
from agents.reminder import service as reminder_service

logger = logging.getLogger(__name__)


class ChatState(TypedDict, total=False):
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


def _assistant_dict(msg) -> dict:
    """Serialize an OpenAI assistant message to the persisted plain-dict form."""
    data = {"role": "assistant", "content": msg.content}
    if msg.tool_calls:
        data["tool_calls"] = [{
            "id": tc.id,
            "type": "function",
            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
        } for tc in msg.tool_calls]
    return data


def _complete(messages, use_tools):
    kwargs = {"model": config.AGENT_MODEL, "messages": messages, "temperature": 0.2}
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


def _model_node(state: ChatState) -> dict:
    msg = _complete(state["messages"], use_tools=True).choices[0].message
    messages = [*state["messages"], _assistant_dict(msg)]
    call = _parse_tool_call(msg)
    update = {"messages": messages, "steps": state.get("steps", 0) + 1,
              "tool_call": call}
    if call is None:
        update.update(status="answer", reply=msg.content or "", pending=None)
    return update


def _route_model(state: ChatState):
    call = state.get("tool_call")
    if call is None:
        return END
    if call["name"] in REMINDER_HANDOFF_TOOLS:
        return "reminder_agent"
    if call["name"] in ENRICH_HANDOFF_TOOLS:
        return "enrich_agent"
    return "read_tool"


def _read_tool_node(state: ChatState) -> dict:
    call = state["tool_call"]
    result = execute_tool(state["ctx"], call["name"], call["args"])
    message = {"role": "tool", "tool_call_id": call["id"], "content": str(result)}
    return {"messages": [*state["messages"], message], "tool_call": None}


def _handoff_node(state: ChatState, agent_name: str, service) -> dict:
    call = state["tool_call"]
    instruction = (call["args"].get("instruction") or "").strip()
    ctx = state["ctx"]
    action = service.plan_action(ctx.user_id, instruction, ctx.now, ctx.tz, ctx.locale)
    if not action:
        message = {"role": "tool", "tool_call_id": call["id"],
                   "content": "No concrete action could be determined."}
        return {"messages": [*state["messages"], message], "tool_call": None,
                "action": None}

    pending = {"tool_call_id": call["id"], "agent": agent_name, "action": action,
               "summary": action["summary"]}
    logger.info("chat handing off to %s: %s user=%s",
                agent_name, action["name"], ctx.user_id)
    return {"status": "confirm", "action": action, "pending": pending,
            "tool_call": None}


def _enrich_agent_node(state: ChatState) -> dict:
    return _handoff_node(state, "enrich", enrich_service)


def _reminder_agent_node(state: ChatState) -> dict:
    return _handoff_node(state, "reminder", reminder_service)


def _route_after_work(state: ChatState):
    if state.get("status") == "confirm":
        return END
    if state.get("steps", 0) >= config.AGENT_MAX_STEPS:
        return "final"
    return "model"


def _resume_action_node(state: ChatState) -> dict:
    pending = state["pending"]
    ctx = state["ctx"]
    if state.get("approve"):
        service = reminder_service if pending.get("agent") == "reminder" else enrich_service
        result = service.execute_action(
            ctx.user_id, pending["action"], ctx.now, ctx.tz, ctx.locale)
    else:
        result = "The user declined this action; do not perform it. Acknowledge and continue."
    message = {"role": "tool", "tool_call_id": pending["tool_call_id"],
               "content": str(result)}
    return {"messages": [*state["messages"], message], "pending": None,
            "action": None, "status": "answer"}


def _final_node(state: ChatState) -> dict:
    msg = _complete(state["messages"], use_tools=False).choices[0].message
    reply = msg.content or "I couldn't finish that in time."
    return {"messages": [*state["messages"], {"role": "assistant", "content": reply}],
            "status": "answer", "reply": reply, "pending": None}


def _entry_route(state: ChatState):
    return "resume_action" if state.get("resume") else "model"


def _build_graph():
    builder = StateGraph(ChatState)
    builder.add_node("model", _model_node)
    builder.add_node("read_tool", _read_tool_node)
    builder.add_node("enrich_agent", _enrich_agent_node)
    builder.add_node("reminder_agent", _reminder_agent_node)
    builder.add_node("resume_action", _resume_action_node)
    builder.add_node("final", _final_node)

    builder.add_conditional_edges(START, _entry_route,
                                  {"model": "model", "resume_action": "resume_action"})
    builder.add_conditional_edges("model", _route_model,
                                  {"read_tool": "read_tool", "enrich_agent": "enrich_agent",
                                   "reminder_agent": "reminder_agent", END: END})
    builder.add_conditional_edges("read_tool", _route_after_work,
                                  {"model": "model", "final": "final", END: END})
    builder.add_conditional_edges("enrich_agent", _route_after_work,
                                  {"model": "model", "final": "final", END: END})
    builder.add_conditional_edges("reminder_agent", _route_after_work,
                                  {"model": "model", "final": "final", END: END})
    builder.add_edge("resume_action", "model")
    builder.add_edge("final", END)
    return builder.compile()


CHAT_GRAPH = _build_graph()


def _invoke(state: ChatState) -> dict:
    limit = max(20, config.AGENT_MAX_STEPS * 3 + 5)
    return CHAT_GRAPH.invoke(state, {"recursion_limit": limit})


def run_loop(ctx, messages: list) -> dict:
    """Run a normal chat turn through the compiled LangGraph workflow."""
    return _invoke({"ctx": ctx, "messages": list(messages), "steps": 0,
                    "pending": None, "action": None, "resume": False})


def resume_action(ctx, messages: list, pending: dict, approve: bool) -> dict:
    """Resume a persisted specialist handoff through the confirmation node."""
    return _invoke({"ctx": ctx, "messages": list(messages), "steps": 0,
                    "pending": pending, "action": pending.get("action"),
                    "resume": True, "approve": bool(approve)})
