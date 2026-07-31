"""
Reminder time + intent extraction (hybrid).

Flow for a message:
1. looks_time_bearing() — cheap gate. If the message has no time signal at all,
   it's not a reminder and the LLM is never called.
2. rule_based_parse() — resolve common Ukrainian/English phrases locally.
   dateparser handles the date/relative anchor (multilingual); the time-of-day
   is resolved by us so part-of-day words get sensible defaults:
   morning/вранці → 09:00, afternoon/вдень → 15:00, evening/ввечері → 19:00,
   night/вночі → 21:00; a bare date defaults to 09:00.
3. If it looks time-bearing but the rules can't pin a time, fall back to the LLM.

Only extraction is implemented here — no storage or delivery.
"""

import re
import json
import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta

import config

logger = logging.getLogger(__name__)

DEFAULT_TZ = config.DEFAULT_TZ
REMINDER_LLM_MODEL = config.REMINDER_LLM_MODEL

# Default clock time when a day is known but no exact time is given.
DEFAULT_TIME = (9, 0)
# Part-of-day words → default time.
PART_OF_DAY = {
    "morning": (9, 0),
    "noon": (12, 0),
    "afternoon": (15, 0),
    "evening": (19, 0),
    "night": (21, 0),
    "tonight": (21, 0),
}
# Ukrainian part-of-day stems → the English key above.
PART_OF_DAY_UA = {
    r"вранці|зранку|ранок|ранку|вранцi": "morning",
    r"опівдні|ополудні": "noon",
    r"вдень|пообіді|після\s+обіду|обід": "afternoon",
    r"ввечері|увечері|вечір|вечором": "evening",
    r"вночі|ніч|вночi": "night",
}

# Words/patterns that make a message "look" time-bearing (gates the LLM call).
TIME_HINT = re.compile(
    r"(remind|reminder|schedule|нагада|нагадай|"
    r"tomorrow|today|tonight|завтра|сьогодні|післязавтра|"
    r"morning|afternoon|evening|night|noon|"
    r"вранці|зранку|ранок|вдень|ввечері|увечері|вечір|вночі|ніч|опівдні|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"понеділ|вівтор|серед|четвер|п.?ятниц|субот|неділ|"
    r"\bin\s+\d|\bчерез\s+\d|\bat\s+\d|\d{1,2}:\d{2}|"
    r"\d{1,2}\s*(am|pm)|(?<![а-яіїєґ])[оo]\s+\d)",
    re.IGNORECASE,
)

# An explicit calendar-date word is present (used to decide "roll to tomorrow").
DATE_HINT = re.compile(
    r"(tomorrow|today|tonight|завтра|сьогодні|післязавтра|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"понеділ|вівтор|серед|четвер|п.?ятниц|субот|неділ)",
    re.IGNORECASE,
)

# Relative offset like "in 30 minutes" / "через 2 години" — trust dateparser's
# exact datetime (both date and time are meaningful).
RELATIVE_HINT = re.compile(r"(?:\bin\b|\bчерез\b)\s+\d+", re.IGNORECASE)


@dataclass
class Reminder:
    is_reminder: bool
    remind_at: datetime | None
    text: str
    source: str  # 'rule' | 'llm' | 'none'


def looks_time_bearing(message: str) -> bool:
    """Cheap check: does the message contain any time/reminder signal?"""
    return bool(TIME_HINT.search(message))


def _parse_clock(text: str) -> tuple[int, int] | None:
    """Return (hour, minute) from an explicit time, else None."""
    t = text.lower()
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)", t)
    if m:
        hour = int(m.group(1)) % 12
        if m.group(3).startswith("p"):
            hour += 12
        return hour, int(m.group(2) or 0)
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", t)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(?:\bat|\bна|(?<![а-яіїєґ])[оo])\s+(\d{1,2})(?::(\d{2}))?", t)
    if m:
        return int(m.group(1)), int(m.group(2) or 0)
    return None


def _part_of_day(text: str) -> tuple[int, int] | None:
    """Return the default time for a part-of-day word, else None."""
    t = text.lower()
    for word, hm in PART_OF_DAY.items():
        if re.search(rf"\b{word}\b", t):
            return hm
    for pattern, key in PART_OF_DAY_UA.items():
        if re.search(pattern, t):
            return PART_OF_DAY[key]
    return None


def _search_anchor(text: str, now: datetime) -> datetime | None:
    """Use dateparser to find a date/relative anchor in free text, tz-aware."""
    try:
        from dateparser.search import search_dates
    except Exception:
        logger.warning("dateparser not installed; rule-based parsing disabled")
        return None

    settings = {
        "PREFER_DATES_FROM": "future",
        "RELATIVE_BASE": now.replace(tzinfo=None),
        "TIMEZONE": str(now.tzinfo),
        "RETURN_AS_TIMEZONE_AWARE": True,
    }
    try:
        found = search_dates(text, languages=["uk", "en"], settings=settings)
    except Exception:
        logger.exception("dateparser search_dates failed")
        return None
    if not found:
        return None

    dt = found[0][1]
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=now.tzinfo)
    return dt.astimezone(now.tzinfo)


def rule_based_parse(text: str, now: datetime) -> datetime | None:
    """Resolve common UA/EN phrases to a concrete datetime, or None.

    dateparser supplies the date anchor; we set the time from an explicit clock,
    a part-of-day default, or the 09:00 fallback.
    """
    anchor = _search_anchor(text, now)

    # Pure relative offset ("in 30 minutes"): keep dateparser's exact datetime.
    if RELATIVE_HINT.search(text) and anchor is not None:
        return anchor

    clock = _parse_clock(text)
    pod = _part_of_day(text)
    explicit_date = bool(DATE_HINT.search(text))

    if anchor is None:
        # No date found, but a time-of-day word might still make this a reminder.
        if clock is None and pod is None:
            return None
        day = now.date()
    else:
        day = anchor.date()

    hour, minute = clock or pod or DEFAULT_TIME
    dt = datetime.combine(day, time(hour, minute), tzinfo=now.tzinfo)

    # Bare time already past today (no explicit date word) → assume tomorrow.
    if not explicit_date and dt <= now:
        dt += timedelta(days=1)
    return dt


def _llm_parse(text: str, now: datetime) -> datetime | None:
    """Fallback extraction via OpenAI. Returns a tz-aware datetime or None."""
    try:
        from openai_client import get_client

        client = get_client()
        system = (
            "Extract a reminder from the user's message. "
            "Return strict JSON: {\"is_reminder\": bool, \"remind_at\": string|null}. "
            "remind_at is ISO-8601 local time with no timezone, e.g. 2026-07-30T09:00:00. "
            f"Current local time is {now.strftime('%Y-%m-%dT%H:%M:%S')} "
            f"({now.tzname()}). Resolve relative expressions against it. "
            "If only a part of day is given, use morning=09:00, noon=12:00, "
            "afternoon=15:00, evening=19:00, night=21:00. If no exact time, use 09:00. "
            "If the message is not asking to be reminded, set is_reminder=false."
        )
        resp = client.chat.completions.create(
            model=REMINDER_LLM_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
        )
        data = json.loads(resp.choices[0].message.content)
        if not data.get("is_reminder") or not data.get("remind_at"):
            return None
        dt = datetime.fromisoformat(data["remind_at"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=now.tzinfo)
        return dt
    except Exception:
        logger.exception("LLM reminder extraction failed")
        return None


def extract_reminder(message: str, now: datetime | None = None) -> Reminder:
    """Hybrid extraction. Returns a Reminder (is_reminder=False when none found)."""
    now = now or datetime.now(DEFAULT_TZ)

    if not looks_time_bearing(message):
        return Reminder(False, None, message, "none")

    dt = rule_based_parse(message, now)
    if dt:
        return Reminder(True, dt, message, "rule")

    dt = _llm_parse(message, now)
    if dt:
        return Reminder(True, dt, message, "llm")

    return Reminder(False, None, message, "none")
