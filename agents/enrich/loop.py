"""LangGraph workflows for the enrichment/action agent.

The turn graph has explicit ``EnrichState`` plus model, read-tool, pending-write,
approval, and final nodes. Conditional edges enforce that reads may loop while
writes pause with a durable interrupt. ``ACTION_PLAN_GRAPH`` is the small stateless
sub-workflow used when the chat agent hands a write instruction to this agent.

Thread messages and pending writes are persisted by the service in PostgreSQL.
Confirmed writes additionally use the shared action-execution ledger so a
retry cannot repeat a side effect.
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
from agents.enrich import db
from agents.enrich.tools import Ctx, TOOL_SPECS, WRITE_TOOLS, execute_tool, summarize_write

logger = logging.getLogger(__name__)


class EnrichState(TypedDict, total=False):
    messages: list[dict]
    context: dict
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


def _ctx(state: EnrichState) -> Ctx:
    data = state["context"]
    return Ctx(
        data["user_id"],
        _restore(data.get("now"), datetime.fromisoformat),
        tz=_restore(data.get("tz"), ZoneInfo),
        locale=data.get("locale") or "en",
    )


def initial_state(ctx: Ctx, messages: list, pending: dict | None = None) -> EnrichState:
    action = None
    if pending:
        action = {"name": pending["name"], "args": pending["args"],
                  "summary": pending["summary"]}
    return {"context": _context_data(ctx), "messages": list(messages), "steps": 0,
            "tool_call": None, "pending": pending, "action": action,
            "completed_action_id": None}


class ActionPlanState(TypedDict, total=False):
    messages: list[dict]
    context: dict
    tool_specs: list[dict]
    steps: int
    tool_call: dict | None
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
    result = execute_tool(_ctx(state), call["name"], call["args"])
    message = {"role": "tool", "tool_call_id": call["id"], "content": str(result)}
    return {"messages": [*state["messages"], message], "tool_call": None}


def _pending_write_node(state: EnrichState) -> dict:
    call = state["tool_call"]
    summary = summarize_write(call["name"], call["args"])
    pending = {"action_id": str(uuid.uuid4()), "tool_call_id": call["id"],
               "name": call["name"],
               "args": call["args"], "summary": summary}
    logger.info("enrich agent pausing for confirmation: %s user=%s",
                call["name"], state["context"]["user_id"])
    action = {"name": call["name"], "args": call["args"], "summary": summary}
    return {"status": "confirm", "action": action, "pending": pending,
            "tool_call": None}


def _route_after_read(state: EnrichState):
    if state.get("steps", 0) >= config.ENRICH_AGENT_MAX_STEPS:
        return "final"
    return "model"


def _approval_node(state: EnrichState) -> dict:
    pending = state["pending"]
    approved = bool(interrupt({
        "action_id": pending["action_id"],
        "agent": "enrich",
        "action": state["action"],
        "summary": pending.get("summary"),
    }))
    ctx = _ctx(state)
    if approved:
        action = {"name": pending["name"], "args": pending["args"],
                  "summary": pending["summary"]}
        result = action_execution.execute_once(
            pending["action_id"], ctx.user_id, "enrich", action,
            lambda: execute_tool(ctx, pending["name"], pending["args"]),
        )
    else:
        result = "The user declined this action; do not perform it. Acknowledge and continue."
    message = {"role": "tool", "tool_call_id": pending["tool_call_id"],
               "content": str(result)}
    return {"messages": [*state["messages"], message], "pending": None,
            "action": None, "completed_action_id": pending["action_id"],
            "status": "answer"}


def _final_node(state: EnrichState) -> dict:
    msg = _complete(state["messages"], use_tools=False).choices[0].message
    reply = msg.content or "I couldn't finish that in time."
    return {"messages": [*state["messages"], {"role": "assistant", "content": reply}],
            "status": "answer", "reply": reply, "pending": None}


def _entry_route(state: EnrichState):
    return "approval" if state.get("pending") else "model"


def build_graph(checkpointer):
    builder = StateGraph(EnrichState)
    builder.add_node("model", _model_node)
    builder.add_node("read_tool", _read_tool_node)
    builder.add_node("pending_write", _pending_write_node)
    builder.add_node("approval", _approval_node)
    builder.add_node("final", _final_node)

    builder.add_conditional_edges(START, _entry_route,
                                  {"model": "model", "approval": "approval"})
    builder.add_conditional_edges("model", _route_model,
                                  {"read_tool": "read_tool", "pending_write": "pending_write",
                                   END: END})
    builder.add_conditional_edges("read_tool", _route_after_read,
                                  {"model": "model", "final": "final"})
    builder.add_edge("pending_write", "approval")
    builder.add_edge("approval", "model")
    builder.add_edge("final", END)
    return builder.compile(checkpointer=checkpointer)


def _plan_model_node(state: ActionPlanState) -> dict:
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
    return {"messages": [*state["messages"], _assistant_dict(msg)],
            "tool_call": call, "steps": state.get("steps", 0) + 1,
            "action": None}


def _route_plan_model(state: ActionPlanState):
    call = state.get("tool_call")
    if call is None:
        return END
    return "validate_write" if call["name"] in WRITE_TOOLS else "plan_read"


def _plan_read_node(state: ActionPlanState) -> dict:
    call = state["tool_call"]
    result = execute_tool(_ctx(state), call["name"], call["args"])
    message = {"role": "tool", "tool_call_id": call["id"], "content": str(result)}
    return {"messages": [*state["messages"], message], "tool_call": None}


def _route_plan_read(state: ActionPlanState):
    return END if state.get("steps", 0) >= config.ENRICH_AGENT_MAX_STEPS else "plan_model"


def _validate_write_node(state: ActionPlanState) -> dict:
    call = state["tool_call"]
    if call["name"] in {"set_note_path", "enrich_note"}:
        try:
            note_id = int(call["args"].get("note_id"))
        except (TypeError, ValueError):
            note_id = None
        if note_id is None or not db.get_note_for_user(_ctx(state).user_id, note_id):
            message = {"role": "tool", "tool_call_id": call["id"],
                       "content": "Error: choose a valid user-owned note id from the handoff or read tools."}
            return {"messages": [*state["messages"], message], "tool_call": None,
                    "action": None}
    return {"action": {"name": call["name"], "args": call["args"],
                       "summary": summarize_write(call["name"], call["args"])},
            "tool_call": None}


def _route_validated(state: ActionPlanState):
    if state.get("action") or state.get("steps", 0) >= config.ENRICH_AGENT_MAX_STEPS:
        return END
    return "plan_model"


def _build_action_plan_graph():
    builder = StateGraph(ActionPlanState)
    builder.add_node("plan_model", _plan_model_node)
    builder.add_node("plan_read", _plan_read_node)
    builder.add_node("validate_write", _validate_write_node)
    builder.add_edge(START, "plan_model")
    builder.add_conditional_edges("plan_model", _route_plan_model,
                                  {"plan_read": "plan_read",
                                   "validate_write": "validate_write", END: END})
    builder.add_conditional_edges("plan_read", _route_plan_read,
                                  {"plan_model": "plan_model", END: END})
    builder.add_conditional_edges("validate_write", _route_validated,
                                  {"plan_model": "plan_model", END: END})
    return builder.compile()


ENRICH_GRAPH = build_graph(InMemorySaver())
ACTION_PLAN_GRAPH = _build_action_plan_graph()


def _invoke(graph, value, graph_config: dict) -> dict:
    limit = max(20, config.ENRICH_AGENT_MAX_STEPS * 3 + 5)
    invoke_config = {**graph_config, "recursion_limit": limit}
    return graph.invoke(value, invoke_config)


def run_loop(ctx, messages: list) -> dict:
    """Run an isolated turn (used by tests) with a memory checkpoint."""
    graph = build_graph(InMemorySaver())
    graph_config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    return _invoke(graph, initial_state(ctx, messages), graph_config)


def resume_write(ctx, messages: list, pending: dict, approve: bool) -> dict:
    """Exercise confirmation in isolation; production resumes its DB checkpoint."""
    graph = build_graph(InMemorySaver())
    graph_config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    _invoke(graph, initial_state(ctx, messages, pending), graph_config)
    return _invoke(graph, Command(resume=bool(approve)), graph_config)


def invoke(graph, graph_config: dict, state: EnrichState) -> dict:
    return _invoke(graph, state, graph_config)


def resume(graph, graph_config: dict, approve: bool) -> dict:
    return _invoke(graph, Command(resume=bool(approve)), graph_config)


def retry(graph, graph_config: dict) -> dict:
    return _invoke(graph, None, graph_config)


def plan_action(ctx: Ctx, messages: list[dict], tool_specs: list[dict]) -> dict | None:
    """Read context as needed, then return one validated, non-executed write."""
    result = ACTION_PLAN_GRAPH.invoke({
        "messages": messages, "context": _context_data(ctx), "tool_specs": tool_specs,
        "steps": 0, "tool_call": None, "action": None,
    })
    return result.get("action")
