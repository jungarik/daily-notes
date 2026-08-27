"""Agentic chat for the Web App chat tab.

A client-agnostic agent that plans, calls tools over the user's own
notes/reminders/links, and answers with citations. See devdoc/agentic-chat.md.

Public entry points (used by the API layer):
- `start_turn(user_id, message, thread_id, ctx)` — run a user message.
- `confirm(user_id, thread_id, approve, ctx)` — resume a paused write.
"""

from agents.chat.service import start_turn, confirm

__all__ = ["start_turn", "confirm"]
