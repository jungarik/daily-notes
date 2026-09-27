"""Composition of the Enricher LangGraph workflow.

One graph now: the stateless `ACTION_PLAN_GRAPH`, which plans one write for a
chat turn. Running it is the agent's `start`; this module only builds.

Two graphs have left this file, and for the same reason both times — a compiled
graph nothing invoked. `ENRICH_GRAPH` was an interactive capture loop with an
`approve` node that paused on a LangGraph `interrupt`; the farm's loop owns the
pause, so it was deleted. `CLASSIFY_GRAPH` was the metadata pipeline offered as
a standalone entry, reachable only from a test; it is now the classifier
agent's own graph (`agents/classifier/graph.py`), which is how those three
nodes finally became reachable in production.

What that leaves here is four nodes: plan, act, link_context, validate_write.
Reminders are their own agent (`agents/reminder/`), and so is filing
(`agents/classifier/`).
"""

from langgraph.graph import END, START, StateGraph

from agents.enricher import routing
from agents.enricher.nodes import act, plan
from agents.enricher.nodes.write import link as write_link
from agents.enricher.nodes.write import validate as write_validate
from agents.enricher.state import ActionPlanState


def _build_action_plan_graph():
    builder = StateGraph(ActionPlanState)
    builder.add_node("plan", plan.run)
    builder.add_node("act", act.run)
    builder.add_node("link_context", write_link.run)
    builder.add_node("validate_write", write_validate.run)

    builder.add_edge(START, "plan")
    builder.add_conditional_edges("plan", routing.after_plan, {
        "act": "act",
        "link_context": "link_context",
        "validate_write": "validate_write",
        END: END,
    })
    builder.add_conditional_edges("act", routing.after_plan_read,
                                  {"plan": "plan", END: END})
    builder.add_edge("link_context", "validate_write")
    builder.add_conditional_edges("validate_write", routing.after_validation,
                                  {"plan": "plan", END: END})

    return builder.compile()


ACTION_PLAN_GRAPH = _build_action_plan_graph()
