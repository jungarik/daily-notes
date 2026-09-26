"""Composition of the Enricher LangGraph workflows.

Two graphs share the same nodes: the stateless `ACTION_PLAN_GRAPH` (plan one
write for a chat turn) and the `CLASSIFY_GRAPH` sub-pipeline it reuses.
Reminders are their own agent (`agents/reminder/`).
Running a compiled graph is the agent's `start`; this module only builds.

There used to be a third, `ENRICH_GRAPH` — an interactive capture loop with an
`approve` node that paused on a LangGraph `interrupt`. Nothing ever invoked it:
the farm's loop owns the pause now, so this agent plans a write, returns
`needs_input`, and performs it in `resume`. It was compiled at import for a
long time after it stopped being reachable, which is a thing every reader had
to rule out. `git log` has it if an in-graph pause is ever wanted back.
"""

from langgraph.graph import END, START, StateGraph

from agents.enricher import routing
from agents.enricher.nodes import act, plan
from agents.enricher.nodes.classify import gather as classify_gather
from agents.enricher.nodes.classify import normalize as classify_normalize
from agents.enricher.nodes.classify import propose as classify_propose
from agents.enricher.nodes.write import link as write_link
from agents.enricher.nodes.write import validate as write_validate
from agents.enricher.state import ActionPlanState, MetadataState


def _add_classify(builder) -> None:
    builder.add_node("classify_gather", classify_gather.run)
    builder.add_node("classify_propose", classify_propose.run)
    builder.add_node("classify_normalize", classify_normalize.run)
    
    builder.add_edge("classify_gather", "classify_propose")
    builder.add_edge("classify_propose", "classify_normalize")


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


def build_classify_graph():
    builder = StateGraph(MetadataState)
    _add_classify(builder)
    builder.add_edge(START, "classify_gather")
    builder.add_edge("classify_normalize", END)

    return builder.compile()


ACTION_PLAN_GRAPH = _build_action_plan_graph()
CLASSIFY_GRAPH = build_classify_graph()
