"""schedule_build node: build the reminder action proposal.

Turns a resolved datetime into a create_reminder action, attaching a referenced
note when the instruction points at one. Single public `run`.
"""

import re
from datetime import datetime

import i18n
from agents.enrich.nodes.schedule import _shared
from agents.enrich.state import EnrichState, ReminderPlanState

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


def _action(contract: dict, remind_at: datetime, locale: str | None) -> dict:
    """Build one reminder proposal from a resolved datetime."""
    instruction = contract["instruction"].strip()
    notes = list((contract.get("resolved_entities") or {}).get(
        "referenced_notes") or [])
    selected = None

    for index, pattern in _ORDINALS:
        if re.search(pattern, instruction, re.IGNORECASE) and index < len(notes):
            selected = notes[index]
            break

    if selected is None and notes and _REFERENCE.search(instruction):
        selected = notes[-1]

    text = instruction

    if selected:
        label = selected.get("title") or " ".join(
            (selected.get("text") or "").split())[:120]
        text = f"{instruction}\nReferenced note: “{label or 'note'}” (id {selected['note_id']})."

    args = {"text": text, "remind_at": remind_at.isoformat()}
    when = i18n.fmt_datetime(locale, remind_at)

    if selected:
        args["note_id"] = int(selected["note_id"])
        summary = i18n.t(locale, "action_create_reminder_note",
                         when=when, text=instruction, id=args["note_id"])
    else:
        summary = i18n.t(locale, "action_create_reminder", when=when, text=instruction)

    return {"name": "create_reminder", "args": args, "summary": summary}


def run(state: ReminderPlanState | EnrichState) -> dict:
    trace = [*(state.get("reminder_trace") or [])]

    try:
        remind_at = _parse_time(state.get("reminder_raw") or {}, _shared.now(state))
        action = (_action(_shared.contract(state), remind_at, _shared.locale(state))
                  if remind_at else None)
        trace.append({"kind": "node", "node": "schedule_build", "status": "ok"})
        update = {"action": action, "reminder_trace": trace}
        call = state.get("tool_call")

        if action and call:
            update["tool_call"] = {**call, "name": action["name"],
                                   "args": action["args"]}
        elif call:
            update["messages"] = [*(state.get("messages") or []), {
                "role": "tool",
                "tool_call_id": call["id"],
                "content": "Error: reminder date/time could not be resolved.",
            }]
            update["tool_call"] = None

        return update
    except Exception as exc:
        trace.append({"kind": "node", "node": "schedule_build",
                      "status": "error", "error": str(exc)})

        return {"action": None, "reminder_error": str(exc),
                "reminder_trace": trace}
