"""LangGraph composition for the finder agent.

Running a compiled graph is `agents.runtime.loop`; this module only builds.

The graph takes no checkpointer. A finder hop never pauses, so it runs start to
finish inside one loop hop, and the hop's durable record is its `agent_states`
row — checkpointing the same turn a second time would buy nothing.

It used to compile with an `InMemorySaver` anyway, which contradicted the line
above and cost more than a contradiction: the agent handed every run a fresh
`thread_id`, so the saver's in-process store gained an entry per turn that
nothing ever read and nothing evicted.
"""

from langgraph.graph import END, START, StateGraph

from agents.finder import routing
from agents.finder.nodes import act, reason
from agents.finder.state import FinderState


def build_graph():
    builder = StateGraph(FinderState)
    builder.add_node("reason", reason.run)
    builder.add_node("act", act.run)
    builder.add_edge(START, "reason")
    builder.add_conditional_edges("reason", routing.after_reason,
                                  {"act": "act", END: END})
    builder.add_edge("act", "reason")

    return builder.compile()


FINDER_GRAPH = build_graph()
