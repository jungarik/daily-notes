"""LangGraph composition for the conversation controller.

Running a compiled graph is `agents.runtime.loop`; this module only builds."""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from agents.conversation import routing
from agents.conversation.nodes import act, approve, handoff, reason
from agents.conversation.state import ChatState


def build_graph(checkpointer):
    builder = StateGraph(ChatState)
    builder.add_node("reason", reason.run)
    builder.add_node("act", act.run)
    builder.add_node("handoff", handoff.run)
    builder.add_node("approve", approve.run)
    builder.add_conditional_edges(START, routing.entry, {"reason": "reason", "approve": "approve"})
    builder.add_conditional_edges("reason", routing.after_reason,
                                  {"act": "act", "handoff": "handoff", END: END})
    builder.add_edge("act", "reason")
    builder.add_conditional_edges("handoff", routing.after_handoff,
                                  {"approve": "approve", "reason": "reason"})
    builder.add_edge("approve", "reason")

    return builder.compile(checkpointer=checkpointer)


CHAT_GRAPH = build_graph(InMemorySaver())
