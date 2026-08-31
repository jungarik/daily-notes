"""Enrichment/action agent — the write/action agent for the user's notes.

A client-agnostic agent that creates notes, creates reminders (from time-bearing
instructions), moves notes, and classifies/enriches note metadata — each with a
confirmation step. Reserved for the web-app capture path; not wired into the bot.
See devdoc/agentic-enrich.md.

Public entry points:
- `start_turn(user_id, message, thread_id, now, tz, locale)` — run an instruction
  (turn-based, for a future direct enrich surface).
- `confirm(user_id, thread_id, approve, now, tz, locale)` — resume a paused write.
- `plan_action(user_id, instruction, now, tz, locale)` — one-shot: the write a
  request implies (used by the chat agent's handoff), without executing.
- `execute_action(user_id, action, now, tz, locale)` — run a planned write.
"""

from agents.enrich.service import start_turn, confirm, plan_action, execute_action

__all__ = ["start_turn", "confirm", "plan_action", "execute_action"]
