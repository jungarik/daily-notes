"""Explicit reminder extraction and proposal nodes."""

import json

import config
from agents.enrich import domain
from agents.enrich.prompts import reminder_extraction_prompt
from agents.enrich.state import (
    EnrichState, ReminderPlanState, context_from_state,
)
from agents.runtime import model_gateway


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
    if not domain.has_reminder_time_hint(instruction):
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
        remind_at = domain.parse_reminder_time(
            state.get("reminder_raw") or {}, _now(state))
        action = (domain.plan_reminder(_contract(state), remind_at)
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
