"""Reminder agent — scheduling as its own vertical.

Owns the datetime-resolution graph, its prompt, its state and its write tool.
Nothing here imports another agent. See `devdoc/agentic-reminder.md`.

`SPEC` is the whole public surface: the loop starts and resumes this agent
through it, and nothing else calls in.
"""

from agents.reminder.agent import SPEC

__all__ = ["SPEC"]
