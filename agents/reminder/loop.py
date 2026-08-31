"""LangGraph planning workflow for the reminder agent.

State carries the instruction, caller clock, parsed time, and proposed action.
``parse_time`` resolves natural language; a conditional edge routes a successful
parse to ``prepare_action`` and an unresolved request directly to END.
"""

import re
from datetime import datetime
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from agents.reminder import domain
from agents.reminder.tools import CREATE_REMINDER, summarize
from agents import handoff


class ReminderState(TypedDict, total=False):
    instruction: str
    handoff: dict
    reminder_text: str
    referenced_note_id: int | None
    now: datetime
    remind_at: datetime | None
    action: dict | None


_ORDINALS = (
    (0, r"\b(first|1st)\b|\bперш(ий|а|е|у)\b"),
    (1, r"\b(second|2nd)\b|\bдруг(ий|а|е|у)\b"),
    (2, r"\b(third|3rd)\b|\bтрет(ій|я|є|ю)\b"),
)
_REFERENCE = re.compile(
    r"\b(that|this|it|one|note)\b|\b(цей|ця|це|цю|той|та|те|його|її|нотатк)\w*\b",
    re.IGNORECASE,
)


def _resolve_reference_node(state: ReminderState) -> dict:
    instruction = state["instruction"].strip()
    entities = (state.get("handoff") or {}).get("resolved_entities") or {}
    notes = list(entities.get("referenced_notes") or [])
    selected = None
    for index, pattern in _ORDINALS:
        if re.search(pattern, instruction, re.IGNORECASE) and index < len(notes):
            selected = notes[index]
            break
    if selected is None and notes and _REFERENCE.search(instruction):
        selected = notes[-1]
    if selected is None:
        return {"reminder_text": instruction, "referenced_note_id": None}
    label = selected.get("title") or " ".join((selected.get("text") or "").split())[:120]
    reminder_text = f"{instruction}\nReferenced note: “{label or 'note'}” (id {selected['note_id']})."
    return {"reminder_text": reminder_text,
            "referenced_note_id": int(selected["note_id"])}


def _parse_time_node(state: ReminderState) -> dict:
    return {"remind_at": domain.extract_time(state["instruction"], state["now"])}


def _route_parsed(state: ReminderState):
    return "prepare_action" if state.get("remind_at") else END


def _prepare_action_node(state: ReminderState) -> dict:
    text, remind_at = state["reminder_text"].strip(), state["remind_at"]
    args = {"text": text, "remind_at": remind_at.isoformat()}
    if state.get("referenced_note_id") is not None:
        args["note_id"] = state["referenced_note_id"]
    return {"action": {"name": CREATE_REMINDER,
                       "args": args,
                       "summary": summarize(text, remind_at)}}


def _build_graph():
    builder = StateGraph(ReminderState)
    builder.add_node("resolve_reference", _resolve_reference_node)
    builder.add_node("parse_time", _parse_time_node)
    builder.add_node("prepare_action", _prepare_action_node)
    builder.add_edge(START, "resolve_reference")
    builder.add_edge("resolve_reference", "parse_time")
    builder.add_conditional_edges("parse_time", _route_parsed,
                                  {"prepare_action": "prepare_action", END: END})
    builder.add_edge("prepare_action", END)
    return builder.compile()


REMINDER_GRAPH = _build_graph()


def plan(request, now: datetime) -> dict | None:
    contract = handoff.normalize(request, now)
    result = REMINDER_GRAPH.invoke(
        {"instruction": contract["instruction"], "handoff": contract,
         "reminder_text": contract["instruction"], "now": now,
         "referenced_note_id": None, "remind_at": None, "action": None})
    return result.get("action")
