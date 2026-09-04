"""Composition and invocation for the Enrich LangGraph workflows.

Four graphs share the same nodes: the interactive `ENRICH_GRAPH` (capture loop),
the stateless `ACTION_PLAN_GRAPH` (plan one write for a chat handoff), and the
`METADATA_GRAPH` / `REMINDER_PLAN_GRAPH` sub-pipelines reused by both.
"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

import config
from agents.enrich import routing
from agents.enrich.nodes import act, approve, plan, reason
from agents.enrich.nodes.classify import gather as classify_gather
from agents.enrich.nodes.classify import normalize as classify_normalize
from agents.enrich.nodes.classify import propose as classify_propose
from agents.enrich.nodes.schedule import build as schedule_build
from agents.enrich.nodes.schedule import resolve as schedule_resolve
from agents.enrich.nodes.write import link as write_link
from agents.enrich.nodes.write import stage as write_stage
from agents.enrich.nodes.write import validate as write_validate
from agents.enrich.state import (
    ActionPlanState, EnrichState, MetadataState, ReminderPlanState, initial_state,
)


def _add_classify(builder) -> None:
    builder.add_node("classify_gather", classify_gather.run)
    builder.add_node("classify_propose", classify_propose.run)
    builder.add_node("classify_normalize", classify_normalize.run)
    builder.add_edge("classify_gather", "classify_propose")
    builder.add_edge("classify_propose", "classify_normalize")


def build_graph(checkpointer):
    builder = StateGraph(EnrichState)
    builder.add_node("reason", reason.run)
    builder.add_node("act", act.run)
    builder.add_node("schedule_resolve", schedule_resolve.run)
    builder.add_node("schedule_build", schedule_build.run)
    builder.add_node("link_context", write_link.run)
    builder.add_node("stage", write_stage.run)
    builder.add_node("approve", approve.run)
    _add_classify(builder)

    builder.add_conditional_edges(START, routing.entry,
                                  {"reason": "reason", "approve": "approve"})
    builder.add_conditional_edges("reason", routing.after_reason, {
        "act": "act",
        "classify_gather": "classify_gather",
        "schedule_resolve": "schedule_resolve",
        "link_context": "link_context",
        "stage": "stage",
        END: END,
    })
    builder.add_edge("act", "reason")
    builder.add_edge("classify_normalize", "stage")
    builder.add_edge("schedule_resolve", "schedule_build")
    builder.add_conditional_edges("schedule_build", routing.after_schedule_build,
                                  {"stage": "stage", "reason": "reason"})
    builder.add_edge("link_context", "stage")
    builder.add_edge("stage", "approve")
    builder.add_edge("approve", "reason")

    return builder.compile(checkpointer=checkpointer)


def _build_action_plan_graph():
    builder = StateGraph(ActionPlanState)
    builder.add_node("plan", plan.run)
    builder.add_node("act", act.run)
    builder.add_node("link_context", write_link.run)
    builder.add_node("validate_write", write_validate.run)
    _add_classify(builder)

    builder.add_edge(START, "plan")
    builder.add_conditional_edges("plan", routing.after_plan, {
        "act": "act",
        "classify_gather": "classify_gather",
        "link_context": "link_context",
        "validate_write": "validate_write",
        END: END,
    })
    builder.add_conditional_edges("act", routing.after_plan_read,
                                  {"plan": "plan", END: END})
    builder.add_edge("classify_normalize", "validate_write")
    builder.add_edge("link_context", "validate_write")
    builder.add_conditional_edges("validate_write", routing.after_validation,
                                  {"plan": "plan", END: END})

    return builder.compile()


def build_metadata_graph():
    builder = StateGraph(MetadataState)
    _add_classify(builder)
    builder.add_edge(START, "classify_gather")
    builder.add_edge("classify_normalize", END)

    return builder.compile()


def build_reminder_plan_graph():
    builder = StateGraph(ReminderPlanState)
    builder.add_node("schedule_resolve", schedule_resolve.run)
    builder.add_node("schedule_build", schedule_build.run)
    builder.add_edge(START, "schedule_resolve")
    builder.add_edge("schedule_resolve", "schedule_build")
    builder.add_edge("schedule_build", END)

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
