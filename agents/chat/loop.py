"""LangGraph workflow for the read-only chat agent and its enrich handoff.

State
-----
``ChatState`` carries the provider message history, per-turn tool context,
current tool call, step budget, pending confirmation, and terminal response.

Nodes
-----
``model`` plans the next step, ``read_tool`` executes a user-scoped read,
``enrich_agent`` and ``reminder_agent`` hand writes to their specialists,
``approval`` interrupts for the user's confirmation and applies its answer,
and ``final`` produces a tool-free fallback.

Edges
-----
START routes a normal turn to ``model`` and legacy pending state to ``approval``.
Model output conditionally routes to a read tool or specialist. Specialist
handoffs lead to the interrupting approval node. A ``Command(resume=...)``
continues at that node and then returns its tool result to the model.

PostgreSQL remains the durable store: thread state is saved at the service
boundary, while confirmed writes are checkpointed in the action-execution
ledger before the graph makes its final model call.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Literal, TypedDict
from zoneinfo import ZoneInfo

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

import config
import openai_client
from agents import action_execution
from agents.chat.tools import (
    Ctx, ENRICH_HANDOFF_TOOLS, REMINDER_HANDOFF_TOOLS, TOOL_SPECS, execute_tool,
)
from agents.enrich import service as enrich_service
from agents.reminder import service as reminder_service

logger = logging.getLogger(__name__)


class ChatState(TypedDict, total=False):
    messages: list[dict]
    context: dict
    citations: list[dict]
    trace: dict
    steps: int
    tool_call: dict | None
    status: Literal["answer", "confirm"]
    reply: str
    action: dict | None
    pending: dict | None
    completed_action_id: str | None


def _context_data(ctx: Ctx) -> dict:
    now = ctx.now.isoformat() if hasattr(ctx.now, "isoformat") else ctx.now
    return {"user_id": ctx.user_id, "now": now, "tz": str(ctx.tz),
            "locale": ctx.locale}


def _restore(value, factory):
    try:
        return factory(value)
    except Exception:
        return value


def _ctx(state: ChatState) -> Ctx:
    data = state["context"]
    ctx = Ctx(
        data["user_id"],
        _restore(data.get("now"), datetime.fromisoformat),
        tz=_restore(data.get("tz"), ZoneInfo),
        locale=data.get("locale") or "en",
    )
    ctx.citations = list(state.get("citations") or [])
    ctx._cited = {item["note_id"] for item in ctx.citations}
    ctx.trace = dict(state.get("trace") or {
        "tools": [], "retrieved_chunks": [], "routes": [],
    })
    return ctx


def _ctx_update(ctx: Ctx) -> dict:
    return {"citations": ctx.citations, "trace": ctx.trace}


def initial_state(ctx: Ctx, messages: list, pending: dict | None = None) -> ChatState:
    return {
        "context": _context_data(ctx), "messages": list(messages), "steps": 0,
        "tool_call": None, "pending": pending,
        "action": pending.get("action") if pending else None,
        "completed_action_id": None,
        "citations": [], "trace": {"tools": [], "retrieved_chunks": [], "routes": []},
    }


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
    ctx = _ctx(state)
    result = execute_tool(ctx, call["name"], call["args"])
    ctx.record_tool(call["name"], call["args"], result)
    ctx.record_route("rag" if call["name"] == "search_notes" else "tool")
    message = {"role": "tool", "tool_call_id": call["id"], "content": str(result)}
    return {"messages": [*state["messages"], message], "tool_call": None,
            **_ctx_update(ctx)}


def _handoff_node(state: ChatState, agent_name: str, service) -> dict:
    call = state["tool_call"]
    instruction = (call["args"].get("instruction") or "").strip()
    ctx = _ctx(state)
    action = service.plan_action(ctx.user_id, instruction, ctx.now, ctx.tz, ctx.locale)
    if hasattr(ctx, "record_tool"):
        ctx.record_tool(call["name"], call["args"], action)
        ctx.record_route(agent_name)
    if not action:
        message = {"role": "tool", "tool_call_id": call["id"],
                   "content": "No concrete action could be determined."}
        return {"messages": [*state["messages"], message], "tool_call": None,
                "action": None, **_ctx_update(ctx)}

    pending = {"action_id": str(uuid.uuid4()), "tool_call_id": call["id"],
               "agent": agent_name, "action": action,
               "summary": action["summary"]}
    logger.info("chat handing off to %s: %s user=%s",
                agent_name, action["name"], ctx.user_id)
    return {"status": "confirm", "action": action, "pending": pending,
            "tool_call": None, **_ctx_update(ctx)}


def _enrich_agent_node(state: ChatState) -> dict:
    return _handoff_node(state, "enrich", enrich_service)


def _reminder_agent_node(state: ChatState) -> dict:
    return _handoff_node(state, "reminder", reminder_service)


def _route_after_read(state: ChatState):
    if state.get("steps", 0) >= config.AGENT_MAX_STEPS:
        return "final"
    return "model"


def _approval_node(state: ChatState) -> dict:
    pending = state["pending"]
    approved = bool(interrupt({
        "action_id": pending["action_id"],
        "agent": pending.get("agent", "enrich"),
        "action": pending["action"],
        "summary": pending.get("summary"),
    }))
    ctx = _ctx(state)
    if approved:
        service = reminder_service if pending.get("agent") == "reminder" else enrich_service
        result = action_execution.execute_once(
            pending["action_id"], ctx.user_id, pending.get("agent", "enrich"),
            pending["action"],
            lambda: service.execute_action(
                ctx.user_id, pending["action"], ctx.now, ctx.tz, ctx.locale),
        )
    else:
        result = "The user declined this action; do not perform it. Acknowledge and continue."
    message = {"role": "tool", "tool_call_id": pending["tool_call_id"],
               "content": str(result)}
    return {"messages": [*state["messages"], message], "pending": None,
            "action": None, "completed_action_id": pending["action_id"],
            "status": "answer", **_ctx_update(ctx)}


def _final_node(state: ChatState) -> dict:
    msg = _complete(state["messages"], use_tools=False).choices[0].message
    reply = msg.content or "I couldn't finish that in time."
    return {"messages": [*state["messages"], {"role": "assistant", "content": reply}],
            "status": "answer", "reply": reply, "pending": None}


def _entry_route(state: ChatState):
    return "approval" if state.get("pending") else "model"


def build_graph(checkpointer):
    builder = StateGraph(ChatState)
    builder.add_node("model", _model_node)
    builder.add_node("read_tool", _read_tool_node)
    builder.add_node("enrich_agent", _enrich_agent_node)
    builder.add_node("reminder_agent", _reminder_agent_node)
    builder.add_node("approval", _approval_node)
    builder.add_node("final", _final_node)

    builder.add_conditional_edges(START, _entry_route,
                                  {"model": "model", "approval": "approval"})
    builder.add_conditional_edges("model", _route_model,
                                  {"read_tool": "read_tool", "enrich_agent": "enrich_agent",
                                   "reminder_agent": "reminder_agent", END: END})
    builder.add_conditional_edges("read_tool", _route_after_read,
                                  {"model": "model", "final": "final"})
    builder.add_edge("enrich_agent", "approval")
    builder.add_edge("reminder_agent", "approval")
    builder.add_edge("approval", "model")
    builder.add_edge("final", END)
    return builder.compile(checkpointer=checkpointer)


CHAT_GRAPH = build_graph(InMemorySaver())


def _invoke(graph, value, graph_config: dict) -> dict:
    limit = max(20, config.AGENT_MAX_STEPS * 3 + 5)
    invoke_config = {**graph_config, "recursion_limit": limit}
    return graph.invoke(value, invoke_config)


def run_loop(ctx, messages: list) -> dict:
    """Run an isolated turn (used by tests/evaluation) with a memory checkpoint."""
    graph = build_graph(InMemorySaver())
    graph_config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    result = _invoke(graph, initial_state(ctx, messages), graph_config)
    ctx.citations = list(result.get("citations") or [])
    ctx.trace = dict(result.get("trace") or ctx.trace)
    return result


def resume_action(ctx, messages: list, pending: dict, approve: bool) -> dict:
    """Exercise a confirmation in isolation; production resumes its DB checkpoint."""
    graph = build_graph(InMemorySaver())
    graph_config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    _invoke(graph, initial_state(ctx, messages, pending), graph_config)
    result = _invoke(graph, Command(resume=bool(approve)), graph_config)
    ctx.citations = list(result.get("citations") or [])
    ctx.trace = dict(result.get("trace") or ctx.trace)
    return result


def invoke(graph, graph_config: dict, state: ChatState) -> dict:
    return _invoke(graph, state, graph_config)


def resume(graph, graph_config: dict, approve: bool) -> dict:
    return _invoke(graph, Command(resume=bool(approve)), graph_config)


def retry(graph, graph_config: dict) -> dict:
    return _invoke(graph, None, graph_config)
