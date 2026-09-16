"""resolve node: resolve the reminder's datetime.

Uses the time already provided by the tool call, else a cheap regex gate before
spending an LLM call to extract one. Single public `run`; it reads state and
makes the one model call, everything below it is pure.
"""

import json
import re

import config
from agents.reminder.prompts import extraction_prompt
from agents.reminder.state import ReminderPlanState, ReminderPlanUpdate
from agents.runtime import model_gateway
from agents.runtime.events import event

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


def _build_request(instruction: str, now) -> dict:
    return {
        "model": config.REMINDER_LLM_MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{
            "role": "system",
            "content": extraction_prompt(now),
        }, {
            "role": "user",
            "content": instruction,
        }],
    }


def run(state: ReminderPlanState) -> ReminderPlanUpdate:
    instruction = state["contract"]["instruction"]

    if not _has_time_hint(instruction):
        return {
            "extracted_time": {"is_reminder": False, "remind_at": None},
            "events": [event("resolve", "skipped")],
        }

    try:
        model_request = _build_request(instruction, state["now"])
        response = model_gateway.chat_completion(**model_request)
        extracted_time = json.loads(response.choices[0].message.content)
    except Exception as exc:
        return {
            "extracted_time": {},
            "events": [event("resolve", "error", error=str(exc))],
        }

    return {
        "extracted_time": extracted_time,
        "events": [event("resolve", "ok")],
    }
