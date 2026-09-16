"""Enrichment/action agent — the write/action agent for the user's notes.

A client-agnostic agent that creates notes, moves notes, and classifies/enriches
note metadata — each with a confirmation step. Reserved for the web-app flow;
not wired into the bot. See devdoc/agentic-enrich.md.

Public entry points:
- `plan_action(user_id, handoff, now, tz, locale)` — one-shot: read context as
  needed and return the validated write a typed Chat handoff implies.
- `execute_action(user_id, action, now, tz, locale)` — run a planned write.
"""

from agents.enrich.handoff_api import execute_action, plan_action

__all__ = [
    "plan_action",
    "execute_action",
]
