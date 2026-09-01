"""Routing, composition, and invocation for the Enrich LangGraph workflows."""

import uuid

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

import config
from agents.enrich.nodes import approval, final, metadata, model, read, reminder, write
from agents.enrich import routing
from agents.enrich.state import (
    ActionPlanState, EnrichState, MetadataState, ReminderPlanState, initial_state,
)


def build_graph(checkpointer):
    builder = StateGraph(EnrichState)
    builder.add_node("model", model.run)
    builder.add_node("read_tool", read.run)
    builder.add_node("metadata_context", metadata.load_context)
    builder.add_node("metadata_model", metadata.propose)
    builder.add_node("metadata_validation", metadata.validate)
    builder.add_node("reminder_model", reminder.extract_time)
    builder.add_node("reminder_validation", reminder.validate)
    builder.add_node("pending_write", write.prepare)
    builder.add_node("approval", approval.run)
    builder.add_node("final", final.run)

    builder.add_conditional_edges(START, routing.entry,
                                  {"model": "model", "approval": "approval"})

    builder.add_conditional_edges("model", routing.after_model,
                                  {"read_tool": "read_tool",
                                   "metadata_context": "metadata_context",
                                   "reminder_model": "reminder_model",
                                   "pending_write": "pending_write", END: END})

    builder.add_conditional_edges("read_tool", routing.after_read,
                                  {"model": "model", "final": "final"})
                                  
    builder.add_edge("metadata_context", "metadata_model")
    builder.add_edge("metadata_model", "metadata_validation")
    builder.add_edge("metadata_validation", "pending_write")
    builder.add_edge("reminder_model", "reminder_validation")
    builder.add_conditional_edges("reminder_validation",
                                  routing.after_reminder_validation,
                                  {"pending_write": "pending_write",
                                   "final": "final"})
    builder.add_edge("pending_write", "approval")
    builder.add_edge("approval", "model")
    builder.add_edge("final", END)

    return builder.compile(checkpointer=checkpointer)


def _build_action_plan_graph():
    builder = StateGraph(ActionPlanState)
    builder.add_node("plan_model", model.plan)
    builder.add_node("plan_read", read.plan)
    builder.add_node("metadata_context", metadata.load_context)
    builder.add_node("metadata_model", metadata.propose)
    builder.add_node("metadata_validation", metadata.validate)
    builder.add_node("validate_write", write.validate)
    builder.add_edge(START, "plan_model")
    builder.add_conditional_edges("plan_model", routing.after_plan_model,
                                  {"plan_read": "plan_read",
                                   "metadata_context": "metadata_context",
                                   "validate_write": "validate_write", 
                                   END: END})
    builder.add_conditional_edges("plan_read", routing.after_plan_read,
                                  {"plan_model": "plan_model", END: END})
    builder.add_edge("metadata_context", "metadata_model")
    builder.add_edge("metadata_model", "metadata_validation")
    builder.add_edge("metadata_validation", "validate_write")
    builder.add_conditional_edges("validate_write", routing.after_validation,
                                  {"plan_model": "plan_model", END: END})
                                  
    return builder.compile()


def build_metadata_graph():
    builder = StateGraph(MetadataState)
    builder.add_node("metadata_context", metadata.load_context)
    builder.add_node("metadata_model", metadata.propose)
    builder.add_node("metadata_validation", metadata.validate)

    builder.add_edge(START, "metadata_context")
    builder.add_edge("metadata_context", "metadata_model")
    builder.add_edge("metadata_model", "metadata_validation")
    builder.add_edge("metadata_validation", END)

    return builder.compile()


def build_reminder_plan_graph():
    builder = StateGraph(ReminderPlanState)
    builder.add_node("reminder_model", reminder.extract_time)
    builder.add_node("reminder_validation", reminder.validate)

    builder.add_edge(START, "reminder_model")
    builder.add_edge("reminder_model", "reminder_validation")
    builder.add_edge("reminder_validation", END)

    return builder.compile()


ENRICH_GRAPH = build_graph(InMemorySaver())
ACTION_PLAN_GRAPH = _build_action_plan_graph()
METADATA_GRAPH = build_metadata_graph()
REMINDER_PLAN_GRAPH = build_reminder_plan_graph()


def _invoke(graph, value, graph_config: dict) -> dict:
    limit = max(20, config.ENRICH_AGENT_MAX_STEPS * 3 + 5)
    return graph.invoke(value, {**graph_config, "recursion_limit": limit})

def invoke(graph, graph_config: dict, state: EnrichState) -> dict:
    return _invoke(graph, state, graph_config)


def resume(graph, graph_config: dict, approve: bool) -> dict:
    return _invoke(graph, Command(resume=bool(approve)), graph_config)


def retry(graph, graph_config: dict) -> dict:
    return _invoke(graph, None, graph_config)
