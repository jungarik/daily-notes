"""
Reminder extraction — the public entry point.

Strategy (implemented in timeparser.py):
1. looks_time_bearing() gates cheaply; no time signal → not a reminder (and no
   LLM call).
2. llm_parse() does the actual parsing with the LLM.

Only extraction lives here — no storage or delivery.
"""

from dataclasses import dataclass
from datetime import datetime

import config
import timeparser


@dataclass
class Reminder:
    is_reminder: bool
    remind_at: datetime | None
    text: str
    source: str  # 'llm' | 'none'


def extract_reminder(message: str, now: datetime | None = None) -> Reminder:
    """Return a Reminder (is_reminder=False when none found)."""
    now = now or datetime.now(config.DEFAULT_TZ)

    if not timeparser.looks_time_bearing(message):
        return Reminder(False, None, message, "none")

    dt = timeparser.llm_parse(message, now)
    if dt:
        return Reminder(True, dt, message, "llm")

    return Reminder(False, None, message, "none")
