"""LangGraph composition and invocation for the conversation controller."""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

import config
from agents.conversation import routing
from agents.conversation.nodes import approval, dispatch, final, model, pre_route, read
from agents.conversation.state import ChatState


def build_graph(checkpointer):
    builder = StateGraph(ChatState)
    builder.add_node("pre_route", pre_route.run)
    builder.add_node("model", model.run)
    builder.add_node("read_tool", read.run)
    builder.add_node("enrich_agent", dispatch.enrich)
    builder.add_node("reminder_agent", dispatch.reminder)
    builder.add_node("approval", approval.run)
    builder.add_node("final", final.run)
    builder.add_conditional_edges(START, routing.entry_route,
                                  {"pre_route": "pre_route", "approval": "approval"})
    builder.add_conditional_edges("pre_route", routing.route_pre,
                                  {"model": "model",
                                   "reminder_agent": "reminder_agent"})
    builder.add_conditional_edges("model", routing.route_model,
                                  {"read_tool": "read_tool", "enrich_agent": "enrich_agent",
                                   "reminder_agent": "reminder_agent", END: END})
    builder.add_conditional_edges("read_tool", routing.route_after_read,
                                  {"model": "model", "final": "final"})
    builder.add_conditional_edges("enrich_agent", routing.route_after_handoff,
                                  {"approval": "approval", "model": "model"})
    builder.add_conditional_edges("reminder_agent", routing.route_after_handoff,
                                  {"approval": "approval", "model": "model"})
    builder.add_edge("approval", "model")
    builder.add_edge("final", END)
    return builder.compile(checkpointer=checkpointer)


CHAT_GRAPH = build_graph(InMemorySaver())


def _invoke(graph, value, graph_config: dict) -> dict:
    limit = max(20, config.AGENT_MAX_STEPS * 3 + 5)
    return graph.invoke(value, {**graph_config, "recursion_limit": limit})


def invoke(graph, graph_config: dict, state: ChatState) -> dict:
    return _invoke(graph, state, graph_config)


def resume(graph, graph_config: dict, decision) -> dict:
    """Resume a paused approval. `decision` is a bool (approve) or a dict
    carrying the approval plus a selection, e.g. {"approve": bool, "selection": [...]}."""
    return _invoke(graph, Command(resume=decision), graph_config)


def retry(graph, graph_config: dict) -> dict:
    return _invoke(graph, None, graph_config)
