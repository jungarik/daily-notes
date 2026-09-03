"""LangGraph composition and invocation for the conversation controller."""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

import config
from agents.conversation import routing
from agents.conversation.nodes import act, approve, handoff, reason
from agents.conversation.state import ChatState


def build_graph(checkpointer):
    builder = StateGraph(ChatState)
    builder.add_node("reason", reason.run)
    builder.add_node("act", act.run)
    builder.add_node("handoff", handoff.run)
    builder.add_node("approve", approve.run)
    builder.add_conditional_edges(START, routing.entry,
                                  {"reason": "reason", "approve": "approve"})
    builder.add_conditional_edges("reason", routing.after_reason,
                                  {"act": "act", "handoff": "handoff", END: END})
    builder.add_edge("act", "reason")
    builder.add_conditional_edges("handoff", routing.after_handoff,
                                  {"approve": "approve", "reason": "reason"})
    builder.add_edge("approve", "reason")

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
