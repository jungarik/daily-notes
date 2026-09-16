"""Reminder agent — scheduling as its own specialist.

Owns the datetime-resolution graph, its prompt, its state and its write tool.
Chat reaches it through the `set_reminder` handoff; the composition root maps
that mode to this agent. Nothing here imports the enrich agent.

Public entry points:
- `plan_action(user_id, handoff, now, tz, locale)` — resolve the time a request
  implies and return the `create_reminder` write, or None.
- `execute_action(user_id, action, now, tz, locale)` — run an approved write.
"""

from agents.reminder.handoff_api import execute_action, plan_action

__all__ = [
    "plan_action",
    "execute_action",
]
