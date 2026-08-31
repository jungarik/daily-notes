"""Public, client-agnostic reminder-agent entry points."""

import logging
from datetime import datetime

from agents.reminder.loop import plan
from agents.reminder.tools import execute

logger = logging.getLogger(__name__)


def plan_action(user_id: int, instruction: str, now: datetime, tz=None,
                locale: str = "en") -> dict | None:
    """Resolve a chat request into one concrete, non-executed reminder write."""
    try:
        return plan(instruction, now)
    except Exception:
        logger.exception("Reminder planning failed for user %s", user_id)
        return None


def execute_action(user_id: int, action: dict, now=None, tz=None,
                   locale: str = "en") -> str:
    """Execute a previously resolved reminder write after confirmation."""
    return execute(user_id, action)
