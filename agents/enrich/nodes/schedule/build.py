"""schedule_build node: build the reminder action proposal.

Turns a resolved datetime into a create_reminder action, attaching a referenced
note when the instruction points at one. Single public `run`; it reads state and
hands plain values to the pure builders below.
"""

import re
from datetime import datetime

import i18n
from agents.enrich.state import EnrichState, ReminderPlanState, context_from_state

_ORDINALS = (
    (0, r"\b(first|1st)\b|\bперш(ий|а|е|у)\b"),
    (1, r"\b(second|2nd)\b|\bдруг(ий|а|е|у)\b"),
    (2, r"\b(third|3rd)\b|\bтрет(ій|я|є|ю)\b"),
)
_REFERENCE = re.compile(
    r"\b(that|this|it|one|note)\b|\b(цей|ця|це|цю|той|та|те|його|її|нотатк)\w*\b",
    re.IGNORECASE)
_UNRESOLVED = "Error: reminder date/time could not be resolved."


def _latest_user_text(messages: list[dict]) -> str:
    for message in reversed(messages or []):
        if message.get("role") == "user":
            return message.get("content") or ""

    return ""


def _contract(state) -> dict:
    existing = state.get("contract")

    if existing:
        return existing

    args = (state.get("tool_call") or {}).get("args") or {}
    instruction = _latest_user_text(state.get("messages") or [])

    if not instruction:
        instruction = (args.get("text") or "").strip()

    resolved = {}

    if args.get("note_id") is not None:
        resolved["referenced_notes"] = [{"note_id": int(args["note_id"])}]

    return {"instruction": instruction, "resolved_entities": resolved}


def _now(state) -> object:
    if state.get("now") is not None:
        return state["now"]

    return context_from_state(state).now


def _locale(state) -> str | None:
    """Locale from EnrichState context or the reminder plan state's own field."""
    context = state.get("context")

    if context and context.get("locale"):
        return context["locale"]

    return state.get("locale")


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


def _traced(trace: list[dict], status: str, error: str | None = None) -> list[dict]:
    entry = {"kind": "node", "node": "schedule_build", "status": status}

    if error is not None:
        entry["error"] = error

    return [*trace, entry]


def _resolved(action: dict, trace: list[dict], tool_call: dict | None) -> dict:
    update = {"action": action, "reminder_trace": trace}

    if tool_call:
        update["tool_call"] = {**tool_call, "name": action["name"],
                               "args": action["args"]}

    return update


def _unresolved(trace: list[dict], tool_call: dict | None,
                messages: list[dict]) -> dict:
    update = {"action": None, "reminder_trace": trace}

    if tool_call:
        update["messages"] = [*messages, {
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "content": _UNRESOLVED,
        }]
        update["tool_call"] = None

    return update


def run(state: ReminderPlanState | EnrichState) -> dict:
    trace = list(state.get("reminder_trace") or [])
    tool_call = state.get("tool_call")
    messages = state.get("messages") or []

    try:
        remind_at = _parse_time(state.get("reminder_raw") or {}, _now(state))
        action = (_action(_contract(state), remind_at, _locale(state))
                  if remind_at else None)
    except Exception as exc:
        return {
            "action": None,
            "reminder_error": str(exc),
            "reminder_trace": _traced(trace, "error", str(exc)),
        }

    trace = _traced(trace, "ok")

    if action:
        return _resolved(action, trace, tool_call)

    return _unresolved(trace, tool_call, messages)
