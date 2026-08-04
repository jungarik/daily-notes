"""
Time/intent parsing internals for reminders.

Everything about *how* a phrase becomes a datetime lives here: the time-bearing
gate, the rule-based parsers (relative offsets, clock, part-of-day, dateparser
anchor) and the LLM fallback. `reminders.py` orchestrates these.
"""

import re
import json
import logging
from datetime import date, datetime, time, timedelta

import config

logger = logging.getLogger(__name__)

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
    r"пізніше|later|кілька|декілька|пару|couple|few|через|"
    r"\bin\s+\d|\bat\s+\d|\d{1,2}:\d{2}|"
    r"\d{1,2}\s*(am|pm)|(?<![а-яіїєґ])[оo]\s+\d)",
    re.IGNORECASE,
)

# Relative-time units (Ukrainian stems + English).
_REL_UNITS = [
    (r"хвилин|хвил|minute|min\b", "minutes"),
    (r"годин|hour|hr\b", "hours"),
    (r"дн(і|ів|я)|день|day", "days"),
    (r"тижн|тиждень|week", "weeks"),
]
# Indefinite quantities → a count. None means "use config.REMINDER_FEW_COUNT".
_FEW_WORDS = {"пару": 2, "couple": 2, "кілька": None, "декілька": None, "few": None}

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
        logger.warning("dateparser not installed; date-anchor parsing disabled")
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


def _duration(spec: str) -> timedelta:
    """Parse a compact duration like '10m', '2h', '1d' into a timedelta."""
    m = re.fullmatch(r"\s*(\d+)\s*([mhd])\s*", spec.lower())
    if not m:
        return timedelta(minutes=10)
    amount, unit = int(m.group(1)), m.group(2)
    return {"m": timedelta(minutes=amount),
            "h": timedelta(hours=amount),
            "d": timedelta(days=amount)}[unit]


def _parse_relative(text: str, now: datetime) -> datetime | None:
    """Handle relative offsets, incl. indefinite quantities and vague 'later'.

    Examples: 'через 5 хвилин', 'через кілька годин', 'in a few days',
    'пізніше'/'later' (→ config.REMINDER_LATER).
    """
    t = text.lower()

    if re.search(r"\bпізніше\b|\blater\b", t):
        return now + _duration(config.REMINDER_LATER)

    m = re.search(
        r"(?:\bчерез|\bin)\s+(\d+|кілька|декілька|пару|a few|few|couple)\s+([^\s,.!?]+)",
        t,
    )
    if not m:
        return None
    qty_word, unit_word = m.group(1).strip(), m.group(2)
    if qty_word.isdigit():
        count = int(qty_word)
    else:
        key = "few" if qty_word == "a few" else qty_word
        few = _FEW_WORDS.get(key)
        count = few if few is not None else config.REMINDER_FEW_COUNT
    for pattern, unit in _REL_UNITS:
        if re.search(pattern, unit_word):
            return now + timedelta(**{unit: count})
    return None


def rule_based_parse(text: str, now: datetime) -> datetime | None:
    """Resolve common UA/EN phrases to a concrete datetime, or None.

    Relative offsets are handled deterministically first; otherwise dateparser
    supplies the date anchor and we set the time from an explicit clock, a
    part-of-day default, or the 09:00 fallback.
    """
    relative = _parse_relative(text, now)
    if relative is not None:
        return relative

    anchor = _search_anchor(text, now)

    # Pure relative offset that dateparser caught: keep its exact datetime.
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


def llm_parse(text: str, now: datetime) -> datetime | None:
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

# A temporal phrase the rule-based range doesn't recognize → hand to the LLM.
_OTHER_TIMEWORD = re.compile(
    r"weekend|month|\bnext\b|\d+\s*(day|week|month)|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"вихідн|місяц|наступн|через\s+\d|"
    r"понеділ|вівтор|серед|четвер|п.?ятниц|субот|неділ",
    re.IGNORECASE,
)


# An explicit range keyword is enough to scope a search by reminder date, even
# without the full agenda-question phrasing (e.g. searching just "today").
_RANGE_KEYWORD = re.compile(
    r"\btoday\b|\btomorrow\b|\bthis\s+week\b|"
    r"\bсьогодні\b|\bзавтра\b|цього\s+тижня|на\s+тиждень",
    re.IGNORECASE,
)


def looks_like_agenda(text: str) -> bool:
    """True if the message reads like a 'what do I have to do' question, or just
    carries an explicit date-range keyword (today / tomorrow / this week)."""
    return bool(AGENDA_HINT.search(text) or _RANGE_KEYWORD.search(text))


def _day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def rule_based_range(text: str, now: datetime):
    """Resolve today/tomorrow/this-week from keywords.

    Returns (start, end, key) with tz-aware bounds (end exclusive), or None when
    some other temporal phrase is present so the LLM can handle it.
    """
    t = text.lower()
    start = _day_start(now)
    if re.search(r"\btomorrow\b|завтра", t):
        start += timedelta(days=1)
        return start, start + timedelta(days=1), "tomorrow"
    if re.search(r"\bweek\b|тижд|тижн", t):
        return start, start + timedelta(days=7), "week"
    if re.search(r"\btoday\b|\btonight\b|сьогодні", t):
        return start, start + timedelta(days=1), "today"
    if _OTHER_TIMEWORD.search(t):
        return None  # e.g. "weekend", "next 3 days", "friday" → LLM
    return start, start + timedelta(days=1), "today"  # plain query → today


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
    """Hybrid agenda parser: text → (start, end, key) range, or None.

    None means the text isn't an agenda question. Otherwise the range is resolved
    by rules first, then the LLM, defaulting to today. `key` is one of
    today / tomorrow / week / range (used to pick the reply header).
    """
    if not looks_like_agenda(text):
        return None
    rng = rule_based_range(text, now)
    if rng is not None:
        return rng
    rng = _llm_range(text, now)
    if rng is not None:
        return rng
    start = _day_start(now)
    return start, start + timedelta(days=1), "today"
