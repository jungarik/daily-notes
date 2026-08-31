"""Write tool owned by the reminder agent."""

import json
import logging
from datetime import datetime

from agents.reminder import domain

logger = logging.getLogger(__name__)

CREATE_REMINDER = "create_reminder"


def summarize(text: str, remind_at: datetime) -> str:
    return "Create a reminder for %s: “%s”." % (remind_at.isoformat(), text.strip())


def execute(user_id: int, action: dict) -> str:
    if action.get("name") != CREATE_REMINDER:
        return "Error: unknown reminder action %s." % action.get("name")
    args = action.get("args") or {}
    text = (args.get("text") or "").strip()
    raw_time = args.get("remind_at")
    if not text or not raw_time:
        return "Error: text and remind_at are required."
    try:
        remind_at = datetime.fromisoformat(raw_time)
        note_id = args.get("note_id")
        result = (domain.attach(user_id, int(note_id), remind_at)
                  if note_id is not None else domain.create(user_id, text, remind_at))
        if result is None:
            return "Error creating reminder: referenced note not found."
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.exception("Reminder action failed for user %s", user_id)
        return "Error creating reminder: %s" % exc
