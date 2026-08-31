"""Reminder agent: parse, plan, and create time-based reminders.

The chat agent uses ``plan_action`` / ``execute_action`` with a confirmation
boundary. This agent is intentionally scoped to the Web App chat tab.
"""

from agents.reminder.service import execute_action, plan_action

__all__ = ["execute_action", "plan_action"]
