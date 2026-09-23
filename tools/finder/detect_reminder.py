"""detect_reminder conversation tool.

A cheap, deterministic classifier the model can call to decide whether a message
is a reminder request — reminder intent plus a time expression — without spending
another model turn on the judgement. Runs pure regex; no LLM, no database.
"""

import re

from agents.contracts import ToolResult

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


def invoke(context: dict, args: dict) -> ToolResult:
    text = (args.get("text") or "").strip()
    intent = bool(_REMINDER_INTENT.search(text))
    has_time_hint = bool(_TIME_HINT.search(text))

    return ToolResult({
        "is_reminder": intent and has_time_hint,
        "intent": intent,
        "has_time_hint": has_time_hint,
    })
