"""Explicit reminder extraction and proposal nodes."""

import json
import re
from datetime import datetime

import config
from agents.enrich.prompts import reminder_extraction_prompt
from agents.enrich.state import (
    EnrichState, ReminderPlanState, context_from_state,
)
from agents.runtime import model_gateway

_ORDINALS = (
    (0, r"\b(first|1st)\b|\bперш(ий|а|е|у)\b"),
    (1, r"\b(second|2nd)\b|\bдруг(ий|а|е|у)\b"),
    (2, r"\b(third|3rd)\b|\bтрет(ій|я|є|ю)\b"),
)
_REFERENCE = re.compile(
    r"\b(that|this|it|one|note)\b|\b(цей|ця|це|цю|той|та|те|його|її|нотатк)\w*\b",
    re.IGNORECASE)
_REL_UNITS = (r"хвилин|хвил|секунд|годин|тижн|тиждень|дн(і|ів|я)|день|"
              r"seconds?|minutes?|\bmin\b|hours?|\bhr\b|days?|weeks?")
_TIME_HINT = re.compile(
    r"(remind|reminder|schedule|нагада|нагадай|"
    r"tomorrow|today|tonight|завтра|сьогодні|післязавтра|"
    r"morning|afternoon|evening|night|noon|"
    r"вранці|зранку|ранок|вдень|ввечері|увечері|вечір|вночі|ніч|опівдні|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"понеділ|вівтор|серед|четвер|п.?ятниц|субот|неділ|"
    r"пізніше|later|кілька|декілька|пару|couple|few|через|"
    rf"{_REL_UNITS}|\bin\s+\d|\bat\s+\d|\d{{1,2}}:\d{{2}}|"
    r"\d{1,2}\s*(am|pm)|(?<![а-яіїєґ])[оo]\s+\d)", re.IGNORECASE)


def _has_time_hint(text: str) -> bool:
    """Cheap gate before the reminder extraction node spends an LLM call."""
    return bool(_TIME_HINT.search(text or ""))


def _parse_reminder_time(data: dict, now: datetime) -> datetime | None:
    """Normalize reminder model output into an aware local datetime."""
    if not data.get("is_reminder") or not data.get("remind_at"):
        return None
    parsed = datetime.fromisoformat(data["remind_at"])
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=now.tzinfo)


def _plan_reminder_action(contract: dict, remind_at: datetime) -> dict | None:
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
    if selected:
        args["note_id"] = int(selected["note_id"])
    return {"name": "create_reminder", "args": args,
            "summary": "Create a reminder for %s: “%s”." %
                       (remind_at.isoformat(), text.strip())}


def _latest_user_text(messages: list[dict]) -> str:
    for message in reversed(messages or []):
        if message.get("role") == "user":
            return message.get("content") or ""
    return ""


def _now(state):
    if state.get("now") is not None:
        return state["now"]
    return context_from_state(state).now


def _contract(state: ReminderPlanState | EnrichState) -> dict:
    if state.get("contract"):
        return state["contract"]
    call = state.get("tool_call") or {}
    args = call.get("args") or {}
    instruction = _latest_user_text(state.get("messages") or [])
    if not instruction:
        instruction = (args.get("text") or "").strip()
    resolved = {}
    if args.get("note_id") is not None:
        resolved["referenced_notes"] = [{"note_id": int(args["note_id"])}]
    return {"instruction": instruction, "resolved_entities": resolved}


def _raw_time_from_tool_call(state: ReminderPlanState | EnrichState):
    call = state.get("tool_call") or {}
    args = call.get("args") or {}
    return args.get("remind_at")


def extract_time(state: ReminderPlanState | EnrichState) -> dict:
    contract = _contract(state)
    instruction = contract["instruction"]
    trace = [*(state.get("reminder_trace") or [])]
    raw_time = _raw_time_from_tool_call(state)
    if raw_time:
        trace.append({"kind": "node", "node": "reminder_model",
                      "status": "provided"})
        return {"reminder_raw": {"is_reminder": True, "remind_at": raw_time},
                "reminder_trace": trace}
    if not _has_time_hint(instruction):
        trace.append({"kind": "node", "node": "reminder_model",
                      "status": "skipped"})
        return {"reminder_raw": {"is_reminder": False, "remind_at": None},
                "reminder_trace": trace}
    try:
        response = model_gateway.chat_completion(
            model=config.REMINDER_LLM_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[{
                "role": "system",
                "content": reminder_extraction_prompt(_now(state))
              }, {
                "role": "user", 
                "content": instruction
              }])
        raw = json.loads(response.choices[0].message.content)
        trace.append({"kind": "node", "node": "reminder_model", "status": "ok"})
        return {"reminder_raw": raw, "reminder_trace": trace}
    except Exception as exc:
        trace.append({"kind": "node", "node": "reminder_model",
                      "status": "error", "error": str(exc)})
        return {"reminder_raw": {}, "reminder_error": str(exc),
                "reminder_trace": trace}


def validate(state: ReminderPlanState | EnrichState) -> dict:
    trace = [*(state.get("reminder_trace") or [])]
    try:
        remind_at = _parse_reminder_time(
            state.get("reminder_raw") or {}, _now(state))
        action = (_plan_reminder_action(_contract(state), remind_at)
                  if remind_at else None)
        trace.append({"kind": "node", "node": "reminder_validation",
                      "status": "ok"})
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
        trace.append({"kind": "node", "node": "reminder_validation",
                      "status": "error", "error": str(exc)})
        return {"action": None, "reminder_error": str(exc),
                "reminder_trace": trace}
