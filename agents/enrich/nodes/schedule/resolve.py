"""schedule_resolve node: resolve the reminder's datetime.

Uses the time already provided by the tool call, else a cheap regex gate before
spending an LLM call to extract one. Single public `run`; it reads state and
makes the one model call, everything below it is pure.
"""

import json
import re

import config
from agents.enrich.prompts import reminder_extraction_prompt
from agents.enrich.state import EnrichState, ReminderPlanState, context_from_state
from agents.runtime import model_gateway

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


def _latest_user_text(messages: list[dict]) -> str:
    for message in reversed(messages or []):
        if message.get("role") == "user":
            return message.get("content") or ""

    return ""


def _instruction(state) -> str:
    existing = state.get("contract")

    if existing:
        return existing["instruction"]

    args = (state.get("tool_call") or {}).get("args") or {}
    instruction = _latest_user_text(state.get("messages") or [])

    if not instruction:
        instruction = (args.get("text") or "").strip()

    return instruction


def _now(state) -> object:
    if state.get("now") is not None:
        return state["now"]

    return context_from_state(state).now


def _has_time_hint(text: str) -> bool:
    """Cheap gate before the extraction node spends an LLM call."""
    return bool(_TIME_HINT.search(text or ""))


def _provided_time(state) -> str | None:
    args = (state.get("tool_call") or {}).get("args") or {}

    return args.get("remind_at")


def _build_request(instruction: str, now) -> dict:
    return {
        "model": config.REMINDER_LLM_MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{
            "role": "system",
            "content": reminder_extraction_prompt(now),
        }, {
            "role": "user",
            "content": instruction,
        }],
    }


def _traced(trace: list[dict], status: str, error: str | None = None) -> list[dict]:
    entry = {"kind": "node", "node": "schedule_resolve", "status": status}

    if error is not None:
        entry["error"] = error

    return [*trace, entry]


def run(state: ReminderPlanState | EnrichState) -> dict:
    trace = list(state.get("reminder_trace") or [])
    raw_time = _provided_time(state)

    if raw_time:
        return {
            "reminder_raw": {"is_reminder": True, "remind_at": raw_time},
            "reminder_trace": _traced(trace, "provided"),
        }

    instruction = _instruction(state)

    if not _has_time_hint(instruction):
        return {
            "reminder_raw": {"is_reminder": False, "remind_at": None},
            "reminder_trace": _traced(trace, "skipped"),
        }

    try:
        model_request = _build_request(instruction, _now(state))
        response = model_gateway.chat_completion(**model_request)
        raw = json.loads(response.choices[0].message.content)
    except Exception as exc:
        return {
            "reminder_raw": {},
            "reminder_error": str(exc),
            "reminder_trace": _traced(trace, "error", str(exc)),
        }

    return {"reminder_raw": raw, "reminder_trace": _traced(trace, "ok")}
