"""
Agenda range parsing for search: "what do I have to do today?" → a date range.

A cheap keyword gate avoids an LLM call on non-agenda queries; anything that
passes is resolved by the LLM. (Reminder-time parsing now lives in enrichment.)
"""

import json
import logging
import re
from datetime import date, datetime, timedelta

import config

logger = logging.getLogger(__name__)

REMINDER_LLM_MODEL = config.REMINDER_LLM_MODEL


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
