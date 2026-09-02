"""Cheap deterministic routing before the Conversation model."""

import json
import re

from agents.conversation.state import ChatState

_REL_UNITS = (
    r"хвилин|хвил|секунд|годин|тижн|тиждень|дн(і|ів|я)|день|"
    r"seconds?|minutes?|\bmin\b|hours?|\bhr\b|days?|weeks?"
)
_TIME_HINT = re.compile(
    r"(remind|reminder|schedule|нагада|нагадай|"
    r"tomorrow|today|tonight|завтра|сьогодні|післязавтра|"
    r"morning|afternoon|evening|night|noon|"
    r"вранці|зранку|ранок|вдень|ввечері|увечері|вечір|вночі|ніч|опівдні|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"понеділ|вівтор|серед|четвер|п.?ятниц|субот|неділ|"
    r"пізніше|later|кілька|декілька|пару|couple|few|через|"
    rf"{_REL_UNITS}|\bin\s+\d|\bat\s+\d|\d{{1,2}}:\d{{2}}|"
    r"\d{1,2}\s*(am|pm)|(?<![а-яіїєґ])[оo]\s+\d)",
    re.IGNORECASE,
)
_REMINDER_INTENT = re.compile(
    r"\b(remind|reminder|schedule)\b|\b(нагада|нагадай|нагадування)\w*",
    re.IGNORECASE,
)


def _is_obvious_reminder_request(text: str) -> bool:
    return bool(_REMINDER_INTENT.search(text or "")) and bool(
        _TIME_HINT.search(text or "")
    )


def _latest_user_text(messages: list[dict]) -> str:
    for message in reversed(messages or []):
        if message.get("role") == "user":
            return message.get("content") or ""
    return ""


def run(state: ChatState) -> dict:
    text = _latest_user_text(state.get("messages") or [])

    if not _is_obvious_reminder_request(text):
        return {"pre_route": None}

    args = {"instruction": text}
    call = {
        "id": "pre-route-reminder",
        "name": "set_reminder",
        "args": args,
    }
    assistant = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": call["id"],
            "type": "function",
            "function": {
                "name": call["name"],
                "arguments": json.dumps(args, ensure_ascii=False),
            },
        }],
    }
    trace = {**(state.get("trace") or {})}
    trace["pre_route"] = "reminder"
    return {
        "messages": [*(state.get("messages") or []), assistant],
        "tool_call": call, 
        "pre_route": "reminder", 
        "trace": trace
      }
