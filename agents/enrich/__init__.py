"""Enrichment agent: classifies a freshly captured note into structured metadata
(type/title/path/tags/priority) using tools over the user's vault, with a one-shot
fallback. See devdoc/agentic-enrich.md.

Public entry point (used by the capture endpoints):
- `enrich(user_id, note_id, text)` — enrich a note in place; returns the metadata.
"""

from agents.enrich.service import enrich

__all__ = ["enrich"]
