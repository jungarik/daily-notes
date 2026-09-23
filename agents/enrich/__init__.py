"""Enrichment/action agent — the write agent for the user's notes.

Creates notes, moves them, tags them, fills in their metadata and curates links
— each with a confirmation step the broker owns. See `devdoc/agentic-enrich.md`.

`SPEC` is the whole public surface: the broker starts and resumes this agent
through it, and nothing else calls in.
"""

from agents.enrich.agent import SPEC

__all__ = ["SPEC"]
