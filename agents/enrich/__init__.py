"""Enrichment/action agent — the write/action agent for the user's notes.

A client-agnostic agent that creates notes, moves notes, and classifies/enriches
note metadata — each with a
confirmation step. Reserved for the web-app capture path; not wired into the bot.
See devdoc/agentic-enrich.md.

Public entry points:
- `start_turn(user_id, message, thread_id, now, tz, locale)` — run an instruction
  (turn-based, for a future direct enrich surface).
- `confirm(user_id, thread_id, approve, now, tz, locale)` — resume a paused write.
- `plan_action(user_id, handoff, now, tz, locale)` — one-shot: read context as
  needed and return the validated write a typed Chat handoff implies.
- `execute_action(user_id, action, now, tz, locale)` — run a planned write.
- `propose_capture` / `revise_capture` / `confirm_capture` / `cancel_capture`
  — standalone fast-capture flow.
"""

from agents.enrich.api import (
    cancel_capture, confirm, confirm_capture, execute_action, plan_action,
    propose_capture, revise_capture, start_turn,
)

__all__ = [
    "start_turn", "confirm", "plan_action", "execute_action",
    "propose_capture", "revise_capture", "confirm_capture", "cancel_capture",
]
