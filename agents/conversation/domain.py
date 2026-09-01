"""Deterministic conversation-routing helpers."""

import re

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
_REMINDER_INTENT = re.compile(
    r"\b(remind|reminder|schedule)\b|\b(нагада|нагадай|нагадування)\w*",
    re.IGNORECASE)


def is_obvious_reminder_request(text: str) -> bool:
    return bool(_REMINDER_INTENT.search(text or "")) and bool(
        _TIME_HINT.search(text or ""))
