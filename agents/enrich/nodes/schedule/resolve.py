"""schedule_resolve node: resolve the reminder's datetime.

Uses the time already provided by the tool call, else a cheap regex gate before
spending an LLM call to extract one. Single public `run`.
"""

import json
import re

import config
from agents.enrich.prompts import reminder_extraction_prompt
from agents.enrich.nodes.schedule import _shared
from agents.enrich.state import EnrichState, ReminderPlanState
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


def _has_time_hint(text: str) -> bool:
    """Cheap gate before the extraction node spends an LLM call."""
    return bool(_TIME_HINT.search(text or ""))


def _raw_time_from_tool_call(state) -> str | None:
    call = state.get("tool_call") or {}
    args = call.get("args") or {}

    return args.get("remind_at")


def run(state: ReminderPlanState | EnrichState) -> dict:
    instruction = _shared.contract(state)["instruction"]
    trace = [*(state.get("reminder_trace") or [])]
    raw_time = _raw_time_from_tool_call(state)

    if raw_time:
        trace.append({"kind": "node", "node": "schedule_resolve",
                      "status": "provided"})

        return {"reminder_raw": {"is_reminder": True, "remind_at": raw_time},
                "reminder_trace": trace}

    if not _has_time_hint(instruction):
        trace.append({"kind": "node", "node": "schedule_resolve",
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
                "content": reminder_extraction_prompt(_shared.now(state)),
            }, {
                "role": "user",
                "content": instruction,
            }])
        raw = json.loads(response.choices[0].message.content)
        trace.append({"kind": "node", "node": "schedule_resolve", "status": "ok"})

        return {"reminder_raw": raw, "reminder_trace": trace}
    except Exception as exc:
        trace.append({"kind": "node", "node": "schedule_resolve",
                      "status": "error", "error": str(exc)})

        return {"reminder_raw": {}, "reminder_error": str(exc),
                "reminder_trace": trace}
