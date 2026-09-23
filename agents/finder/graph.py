"""LangGraph composition for the finder agent.

Running a compiled graph is `agents.runtime.loop`; this module only builds.

The graph takes no checkpointer. A finder hop never pauses, so it runs start to
finish inside one loop hop, and the hop's durable record is its `agent_states`
row — checkpointing the same turn a second time would buy nothing.
"""

from langgraph.checkpoint.memory import InMemorySaver
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

    return builder.compile(checkpointer=InMemorySaver())


FINDER_GRAPH = build_graph()
