"""Enrichment/action agent — the write agent for the user's notes.

Creates notes, moves them, tags them, fills in their metadata and curates links
— each with a confirmation step the loop owns. See `devdoc/agentic-enricher.md`.

`SPEC` is the whole public surface: the loop starts and resumes this agent
through it, and nothing else calls in.
"""

from agents.enricher.agent import SPEC

__all__ = ["SPEC"]
