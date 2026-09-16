"""Composition of the reminder planning graph.

    START ─▶ resolve ─▶ build ─▶ END

`resolve` turns an instruction into a datetime, `build` turns that datetime into
a `create_reminder` proposal. Stateless: it plans, it never writes.

The graph declares `ReminderPlanOutput` as its output schema, so `invoke`
returns `{"action": ...}` rather than the whole working state — the caller reads
a contract instead of picking a key out of everything the nodes happened to
leave behind. Nodes may still write any channel; the schema only filters what
comes back.
"""

from langgraph.graph import END, START, StateGraph

from agents.reminder.nodes import build, resolve
from agents.reminder.state import ReminderPlanOutput, ReminderPlanState


def build_plan_graph():
    builder = StateGraph(ReminderPlanState, output_schema=ReminderPlanOutput)
    builder.add_node("resolve", resolve.run)
    builder.add_node("build", build.run)
    builder.add_edge(START, "resolve")
    builder.add_edge("resolve", "build")
    builder.add_edge("build", END)

    return builder.compile()


PLAN_GRAPH = build_plan_graph()
