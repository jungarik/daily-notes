"""Public, client-agnostic reminder-agent entry points."""

import logging
from datetime import datetime

from agents import handoff
from agents.reminder import db
from agents.reminder.loop import plan
from agents.reminder.tools import execute

logger = logging.getLogger(__name__)


def plan_action(user_id: int, request, now: datetime, tz=None,
                locale: str = "en") -> dict | None:
    """Resolve a chat request into one concrete, non-executed reminder write."""
    try:
        contract = handoff.normalize(request, now, tz, locale)
        notes = []
        for note_id in contract["referenced_note_ids"]:
            note = db.get_note_for_user(user_id, note_id)
            if note:
                notes.append(note)
        contract["resolved_entities"]["referenced_notes"] = notes
        return plan(contract, now)
    except Exception:
        logger.exception("Reminder planning failed for user %s", user_id)
        return None


def execute_action(user_id: int, action: dict, now=None, tz=None,
                   locale: str = "en") -> str:
    """Execute a previously resolved reminder write after confirmation."""
    return execute(user_id, action)
