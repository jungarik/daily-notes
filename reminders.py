"""
Reminder extraction — the public entry point.

Hybrid strategy (implemented in timeparser.py):
1. looks_time_bearing() gates cheaply; no time signal → not a reminder.
2. rule_based_parse() resolves common Ukrainian/English phrases locally.
3. llm_parse() is the fallback when it looks time-bearing but rules can't pin it.

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
    source: str  # 'rule' | 'llm' | 'none'


def extract_reminder(message: str, now: datetime | None = None) -> Reminder:
    """Hybrid extraction. Returns a Reminder (is_reminder=False when none found)."""
    now = now or datetime.now(config.DEFAULT_TZ)

    if not timeparser.looks_time_bearing(message):
        return Reminder(False, None, message, "none")

    dt = timeparser.rule_based_parse(message, now)
    if dt:
        return Reminder(True, dt, message, "rule")

    dt = timeparser.llm_parse(message, now)
    if dt:
        return Reminder(True, dt, message, "llm")

    return Reminder(False, None, message, "none")
