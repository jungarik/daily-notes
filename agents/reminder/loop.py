"""LangGraph planning workflow for the reminder agent.

State carries the instruction, caller clock, parsed time, and proposed action.
``parse_time`` resolves natural language; a conditional edge routes a successful
parse to ``prepare_action`` and an unresolved request directly to END.
"""

from datetime import datetime
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from agents.reminder import domain
from agents.reminder.tools import CREATE_REMINDER, summarize


class ReminderState(TypedDict, total=False):
    instruction: str
    now: datetime
    remind_at: datetime | None
    action: dict | None


def _parse_time_node(state: ReminderState) -> dict:
    return {"remind_at": domain.extract_time(state["instruction"], state["now"])}


def _route_parsed(state: ReminderState):
    return "prepare_action" if state.get("remind_at") else END


def _prepare_action_node(state: ReminderState) -> dict:
    text, remind_at = state["instruction"].strip(), state["remind_at"]
    return {"action": {"name": CREATE_REMINDER,
                       "args": {"text": text, "remind_at": remind_at.isoformat()},
                       "summary": summarize(text, remind_at)}}


def _build_graph():
    builder = StateGraph(ReminderState)
    builder.add_node("parse_time", _parse_time_node)
    builder.add_node("prepare_action", _prepare_action_node)
    builder.add_edge(START, "parse_time")
    builder.add_conditional_edges("parse_time", _route_parsed,
                                  {"prepare_action": "prepare_action", END: END})
    builder.add_edge("prepare_action", END)
    return builder.compile()


REMINDER_GRAPH = _build_graph()


def plan(instruction: str, now: datetime) -> dict | None:
    result = REMINDER_GRAPH.invoke(
        {"instruction": instruction, "now": now, "remind_at": None, "action": None})
    return result.get("action")
