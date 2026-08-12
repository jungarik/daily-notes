"""
Reminder-time extraction for the fast capture path.

A cheap keyword gate avoids an LLM call on notes with no time signal; anything
that passes is parsed by the LLM. Returns a tz-aware datetime or None. (Richer
note metadata is handled separately, on demand, by enrichment.py.)
"""

import re
import json
import logging
from datetime import datetime, timedelta

import config
from services import user_service
from stores import reminder_store
from openai_client import get_client

logger = logging.getLogger(__name__)

# Relative-time unit stems (Ukrainian + English).
_REL_UNITS = (
    r"хвилин|хвил|секунд|годин|тижн|тиждень|дн(і|ів|я)|день|"
    r"seconds?|minutes?|\bmin\b|hours?|\bhr\b|days?|weeks?"
)

# Cheap gate: does the message look time-bearing?
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


def extract_reminder(text: str, now: datetime) -> datetime | None:
    """Return the reminder time for a note, or None. Gated + LLM-parsed."""
    if not looks_time_bearing(text):
        return None
    try:
        system = (
            "Extract a reminder from the user's message (Ukrainian or English). "
            "Return strict JSON: {\"is_reminder\": bool, \"remind_at\": string|null}. "
            "remind_at is ISO-8601 local time with no timezone, e.g. 2026-07-30T09:00:00. "
            f"Current local time is {now.strftime('%Y-%m-%dT%H:%M:%S')} ({now.tzname()}). "
            "Resolve all relative expressions against it. If only a part of day is "
            "given, use morning=09:00, noon=12:00, afternoon=15:00, evening=19:00, "
            "night=21:00. If a date has no time, use 09:00. For an indefinite quantity "
            f"('кілька'/'a few') assume about {config.REMINDER_FEW_COUNT}. For a vague "
            f"'later'/'пізніше', schedule about {config.REMINDER_LATER} from now. "
            "If the message is not asking to be reminded, set is_reminder=false."
        )
        resp = get_client().chat.completions.create(
            model=config.REMINDER_LLM_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
        )
        content = resp.choices[0].message.content
        logger.info("Reminder LLM | input=%r | response=%r", text, content)
        data = json.loads(content)
        if not data.get("is_reminder") or not data.get("remind_at"):
            return None
        dt = datetime.fromisoformat(data["remind_at"])
        return dt if dt.tzinfo else dt.replace(tzinfo=now.tzinfo)
    except Exception:
        logger.exception("Reminder extraction failed")
        return None


def detect_reminder(note_id: int, user_id: int, text: str, now: datetime):
    """If the note is time-bearing, create a reminder for it. Returns
    (reminder_id, remind_at) or None."""
    remind_at = extract_reminder(text, now)
    if not remind_at:
        return None
    reminder_id = reminder_store.create_reminder(note_id, user_id, remind_at)
    logger.info(
        "Reminder %s created for note %s at %s",
        reminder_id, note_id, remind_at.isoformat(),
    )
    return reminder_id, remind_at


# Hour a "tomorrow" snooze lands on, in the user's timezone.
SNOOZE_TOMORROW_HOUR = 9


def cancel(reminder_id: int) -> None:
    """Cancel a reminder so it never fires."""
    reminder_store.set_status(reminder_id, "canceled")
    logger.info("Reminder %s canceled", reminder_id)


def mark_done(reminder_id: int) -> None:
    """Mark a reminder delivered/handled."""
    reminder_store.set_status(reminder_id, "done")
    logger.info("Reminder %s marked done", reminder_id)


def snooze(reminder_id: int, user_id: int, mode: str) -> datetime:
    """Postpone a reminder. `mode` is 'tomorrow' (→ next day at SNOOZE_TOMORROW_HOUR
    in the user's timezone) or a number of minutes from now. Returns the new time.
    """
    tz = user_service.timezone(user_id)
    now = datetime.now(tz)
    if mode == "tomorrow":
        new_time = (now + timedelta(days=1)).replace(
            hour=SNOOZE_TOMORROW_HOUR, minute=0, second=0, microsecond=0,
        )
    else:
        new_time = now + timedelta(minutes=int(mode))
    reminder_store.postpone(reminder_id, new_time)
    logger.info("Reminder %s snoozed to %s", reminder_id, new_time.isoformat())
    return new_time
