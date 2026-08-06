"""
Time parsing for reminders and agenda ranges.

Reminder datetimes are parsed by the LLM only (a cheap keyword gate avoids
calling it on messages with no time signal). Agenda ranges use simple rules for
today/tomorrow/this week with an LLM fallback for anything else.
"""

import re
import json
import logging
from datetime import date, datetime, timedelta

import config

logger = logging.getLogger(__name__)

REMINDER_LLM_MODEL = config.REMINDER_LLM_MODEL

# Relative-time unit stems (Ukrainian + English); part of the gate below.
_REL_UNITS = (
    r"хвилин|хвил|секунд|годин|тижн|тиждень|дн(і|ів|я)|день|"
    r"seconds?|minutes?|\bmin\b|hours?|\bhr\b|days?|weeks?"
)

# Cheap gate: words/patterns that make a message "look" time-bearing, so we only
# spend an LLM call when the message plausibly contains a reminder time.
TIME_HINT = re.compile(
    r"(remind|reminder|schedule|нагада|нагадай|"
    r"tomorrow|today|tonight|завтра|сьогодні|післязавтра|"
    r"morning|afternoon|evening|night|noon|"
    r"вранці|зранку|ранок|вдень|ввечері|увечері|вечір|вночі|ніч|опівдні|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"понеділ|вівтор|серед|четвер|п.?ятниц|субот|неділ|"
    r"пізніше|later|кілька|декілька|пару|couple|few|через|"
    rf"{_REL_UNITS}|"
    r"\bin\s+\d|\bat\s+\d|\d{1,2}:\d{2}|"
    r"\d{1,2}\s*(am|pm)|(?<![а-яіїєґ])[оo]\s+\d)",
    re.IGNORECASE,
)


def looks_time_bearing(message: str) -> bool:
    """Cheap check: does the message contain any time/reminder signal?"""
    return bool(TIME_HINT.search(message))


def llm_parse(text: str, now: datetime) -> datetime | None:
    """Parse a reminder time from text via the LLM. Returns tz-aware dt or None."""
    try:
        from openai_client import get_client

        client = get_client()
        system = (
            "Extract a reminder from the user's message (Ukrainian or English). "
            "Return strict JSON: {\"is_reminder\": bool, \"remind_at\": string|null}. "
            "remind_at is ISO-8601 local time with no timezone, e.g. 2026-07-30T09:00:00. "
            f"Current local time is {now.strftime('%Y-%m-%dT%H:%M:%S')} "
            f"({now.tzname()}). Resolve all relative expressions against it. "
            "If only a part of day is given, use morning=09:00, noon=12:00, "
            "afternoon=15:00, evening=19:00, night=21:00. If a date has no time, use 09:00. "
            f"For an indefinite quantity ('кілька'/'декілька'/'a few') assume about "
            f"{config.REMINDER_FEW_COUNT} of the unit. For a vague 'later'/'пізніше', "
            f"schedule about {config.REMINDER_LATER} from now (10m=minutes, 1h=hours, 1d=days). "
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
        content = resp.choices[0].message.content
        logger.info("Reminder LLM | input=%r | response=%s", text, content)
        data = json.loads(content)
        if not data.get("is_reminder") or not data.get("remind_at"):
            return None
        dt = datetime.fromisoformat(data["remind_at"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=now.tzinfo)
        logger.info("Reminder LLM | resolved remind_at=%s", dt.isoformat())
        return dt
    except Exception:
        logger.exception("LLM reminder extraction failed")
        return None


# --- Agenda ranges ("what do I have to do today?") --------------------------

# Phrases that signal an agenda / to-do question (Ukrainian + English).
AGENDA_HINT = re.compile(
    r"what\s+(do\s+i\s+have\s+to\s+do|to\s+do|should\s+i\s+do|'?s\s+on)|"
    r"\bmy\s+(tasks|to-?dos|agenda|plans)\b|"
    r"\bto-?do\b|"
    r"що\s+(мені\s+)?(треба\s+|потрібно\s+|маю\s+)?(з)?робити|"
    r"мо[її]\s+(завдання|справи|плани)|"
    r"план[иі]\s+на|"
    r"що\s+(в\s+мене\s+)?на\s+(сьогодні|завтра|тиждень)",
    re.IGNORECASE,
)

# An explicit range keyword scopes a search by reminder date even without the
# full agenda-question phrasing (e.g. searching just "today", "this weekend",
# "next 3 days"). Also gates the (LLM) range parse.
_RANGE_KEYWORD = re.compile(
    r"\btoday\b|\btomorrow\b|\btonight\b|\bweek\b|weekend|month|\bnext\b|"
    r"\d+\s*(day|week|month)|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"сьогодні|завтра|тижд|тижн|вихідн|місяц|наступн|"
    r"понеділ|вівтор|серед|четвер|п.?ятниц|субот|неділ",
    re.IGNORECASE,
)


def looks_like_agenda(text: str) -> bool:
    """True if the message reads like a 'what do I have to do' question, or just
    carries an explicit date-range keyword (today / this week / weekend / ...)."""
    return bool(AGENDA_HINT.search(text) or _RANGE_KEYWORD.search(text))


def _day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _llm_range(text: str, now: datetime):
    """LLM fallback: (start, end, 'range') for arbitrary phrasings, or None."""
    try:
        from openai_client import get_client

        client = get_client()
        system = (
            "The user asks what they need to do over some period. "
            "Return strict JSON {\"start\": \"YYYY-MM-DD\", \"end\": \"YYYY-MM-DD\"} "
            "for the inclusive date range they mean. "
            f"Today is {now.strftime('%Y-%m-%d')} ({now.tzname()}). "
            "If unclear, use today for both dates."
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
        start_d = date.fromisoformat(data["start"])
        end_d = date.fromisoformat(data["end"])
        tz = now.tzinfo
        start = datetime(start_d.year, start_d.month, start_d.day, tzinfo=tz)
        end = datetime(end_d.year, end_d.month, end_d.day, tzinfo=tz) + timedelta(days=1)
        return start, end, "range"
    except Exception:
        logger.exception("LLM agenda range failed")
        return None


def parse_agenda(text: str, now: datetime):
    """Agenda range parser: text → (start, end, key) range, or None.

    A cheap keyword gate first avoids an LLM call on non-agenda queries; anything
    that passes is parsed by the LLM, defaulting to today if it can't decide.
    `key` is 'range' (LLM) or 'today' (fallback); only the bounds are used.
    """
    if not looks_like_agenda(text):
        return None
    rng = _llm_range(text, now)
    if rng is not None:
        return rng
    start = _day_start(now)
    return start, start + timedelta(days=1), "today"
