"""build node: build the reminder action proposal.

Turns a resolved datetime into a create_reminder action, attaching a referenced
note when the instruction points at one. Single public `run`; it reads state and
hands plain values to the pure builders below.
"""

import re
from datetime import datetime

import i18n
from agents.reminder.state import ReminderPlanState, ReminderPlanUpdate
from agents.runtime.events import event

_ORDINALS = (
    (0, r"\b(first|1st)\b|\bперш(ий|а|е|у)\b"),
    (1, r"\b(second|2nd)\b|\bдруг(ий|а|е|у)\b"),
    (2, r"\b(third|3rd)\b|\bтрет(ій|я|є|ю)\b"),
)
_REFERENCE = re.compile(
    r"\b(that|this|it|one|note)\b|\b(цей|ця|це|цю|той|та|те|його|її|нотатк)\w*\b",
    re.IGNORECASE)


def _parse_time(data: dict, now: datetime) -> datetime | None:
    """Normalize reminder model output into an aware local datetime."""
    if not data.get("is_reminder") or not data.get("remind_at"):
        return None

    parsed = datetime.fromisoformat(data["remind_at"])

    return parsed if parsed.tzinfo else parsed.replace(tzinfo=now.tzinfo)


def _referenced_note(instruction: str, notes: list[dict]) -> dict | None:
    """The note the instruction points at — by ordinal, else the last mentioned."""
    for index, pattern in _ORDINALS:
        if re.search(pattern, instruction, re.IGNORECASE) and index < len(notes):
            return notes[index]

    if notes and _REFERENCE.search(instruction):
        return notes[-1]

    return None


def _action(contract: dict, remind_at: datetime, locale: str | None) -> dict:
    """Build one reminder proposal from a resolved datetime."""
    instruction = contract["instruction"].strip()
    notes = list((contract.get("resolved_entities") or {}).get(
        "referenced_notes") or [])
    selected = _referenced_note(instruction, notes)
    text = instruction
    when = i18n.fmt_datetime(locale, remind_at)

    if not selected:
        return {
            "name": "create_reminder",
            "args": {"text": text, "remind_at": remind_at.isoformat()},
            "summary": i18n.t(locale, "action_create_reminder",
                              when=when, text=instruction),
        }

    label = selected.get("title") or " ".join(
        (selected.get("text") or "").split())[:120]
    text = f"{instruction}\nReferenced note: “{label or 'note'}” (id {selected['note_id']})."
    note_id = int(selected["note_id"])

    return {
        "name": "create_reminder",
        "args": {"text": text, "remind_at": remind_at.isoformat(), "note_id": note_id},
        "summary": i18n.t(locale, "action_create_reminder_note",
                          when=when, text=instruction, id=note_id),
    }


def run(state: ReminderPlanState) -> ReminderPlanUpdate:
    try:
        remind_at = _parse_time(state.get("extracted_time") or {}, state["now"])
        action = (_action(state["contract"], remind_at, state.get("locale"))
                  if remind_at else None)
    except Exception as exc:
        return {
            "action": None,
            "events": [event("build", "error", error=str(exc))],
        }

    return {
        "action": action,
        "events": [event("build", "ok")],
    }
