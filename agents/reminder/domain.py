"""Reminder interpretation and creation logic (no raw SQL)."""

import json
import logging
import re
from datetime import datetime

import config
from openai_client import get_client
from agents.reminder import db

logger = logging.getLogger(__name__)

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


def extract_time(text: str, now: datetime) -> datetime | None:
    """Resolve a reminder request to an aware local datetime.

    The cheap hint gate prevents ordinary notes from invoking the model.
    """
    if not _TIME_HINT.search(text or ""):
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
            "If the message is not asking to be reminded, set is_reminder=false.")
        response = get_client().chat.completions.create(
            model=config.REMINDER_LLM_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": text}],
        )
        data = json.loads(response.choices[0].message.content)
        if not data.get("is_reminder") or not data.get("remind_at"):
            return None
        parsed = datetime.fromisoformat(data["remind_at"])
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=now.tzinfo)
    except Exception:
        logger.exception("Reminder extraction failed")
        return None


def _chunk_text(text: str, size: int = config.CHUNK_SIZE,
                overlap: int = config.CHUNK_OVERLAP) -> list[str]:
    text = text.strip()
    if len(text) <= size:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + size])
        start += size - overlap
    return chunks


def _build_chunks(text: str) -> list[dict]:
    chunks = []
    for index, content in enumerate(_chunk_text(text)):
        response = get_client().embeddings.create(model=config.EMBED_MODEL, input=content)
        chunks.append({"index": index, "content": content,
                       "token_count": len(content.split()),
                       "metadata": {"char_len": len(content)},
                       "embedding": str(response.data[0].embedding)})
    return chunks


def create(user_id: int, text: str, remind_at: datetime) -> dict:
    """Create the reminder's backing note and reminder after confirmation."""
    chunks = _build_chunks(text)
    note_id, reminder_id = db.create_note_with_reminder(
        user_id, text, chunks, remind_at)
    logger.info("Reminder agent created reminder %s for user %s", reminder_id, user_id)
    return {"note_id": note_id, "reminder_id": reminder_id,
            "remind_at": remind_at.isoformat()}


def attach(user_id: int, note_id: int, remind_at: datetime) -> dict | None:
    """Attach a reminder to an existing user-owned note."""
    reminder_id = db.attach_reminder(user_id, note_id, remind_at)
    if reminder_id is None:
        return None
    logger.info("Reminder agent attached reminder %s to note %s (user %s)",
                reminder_id, note_id, user_id)
    return {"note_id": note_id, "reminder_id": reminder_id,
            "remind_at": remind_at.isoformat()}
