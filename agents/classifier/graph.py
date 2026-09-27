"""Composition of the classifier workflow.

    START ─▶ gather ─▶ propose ─▶ normalize ─▶ END

Three nodes, no conditional edges: filing a note is a fixed pipeline — read the
note and the vault it is filed into, ask the model, canonicalise the answer.
There is nothing to branch on, so `routing.py` would hold no predicates and the
module is absent rather than empty.

This graph is the one the enricher compiled as `CLASSIFY_GRAPH` and never
invoked. It was reachable only from a test for as long as it existed; giving
it an agent is what makes it live.

Running a compiled graph is the agent's `start`; this module only builds.
"""

from langgraph.graph import END, START, StateGraph

from agents.classifier.nodes import gather, normalize, propose
from agents.classifier.state import ClassifyState


def _build_graph():
    builder = StateGraph(ClassifyState)
    builder.add_node("gather", gather.run)
    builder.add_node("propose", propose.run)
    builder.add_node("normalize", normalize.run)

    builder.add_edge(START, "gather")
    builder.add_edge("gather", "propose")
    builder.add_edge("propose", "normalize")
    builder.add_edge("normalize", END)

    return builder.compile()


CLASSIFY_GRAPH = _build_graph()
