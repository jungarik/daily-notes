"""Agentic chat for the Web App chat tab.

A client-agnostic agent that plans, calls read tools over the user's own
notes/reminders/links, and answers with citations. It performs no writes itself:
when the user asks it to act, it hands off to the enrich (action) agent, which
proposes the change for the user to confirm. See devdoc/agentic-chat.md.

Public entry points (used by the API layer):
- `start_turn(user_id, message, thread_id, now, tz, locale)` — run a user message.
- `confirm(user_id, thread_id, approve, now, tz, locale)` — resume a paused action.
"""

from agents.chat.service import start_turn, confirm

__all__ = ["start_turn", "confirm"]
