"""
Search / question-answering domain service.

Wraps agenda-range detection around the RAG answer so callers (any client) only
pass the raw query. Keeps `semantic` pure (it doesn't know about agenda parsing).
"""

import logging
from datetime import datetime

from services import semantic
from services import timeparser

logger = logging.getLogger(__name__)


def answer(user_id: int, query: str, now: datetime,
           language: str = "en", tz=None) -> str | None:
    """Return a natural-language RAG answer. If the query reads like an agenda
    ('what do I have today'), scope it to reminders due in that range."""
    agenda_range = timeparser.parse_agenda(query, now)
    start, end = agenda_range[:2] if agenda_range else (None, None)
    if agenda_range:
        logger.info("Agenda query for user %s scoped to %s..%s", user_id, start, end)
    return semantic.answer(
        user_id, query,
        remind_start=start, remind_end=end,
        language=language, tz=tz,
    )


def answer_with_sources(user_id: int, query: str, now: datetime,
                        language: str = "en", tz=None) -> tuple[str | None, list[int]]:
    """Like `answer`, but also returns the note ids the answer drew on (so the
    agent can cite them). Retrieves once and reuses the hits — no double embed.
    Returns (answer_text | None, [note_id, …] most-relevant first)."""
    agenda_range = timeparser.parse_agenda(query, now)
    start, end = agenda_range[:2] if agenda_range else (None, None)
    hits = semantic.search(user_id, query, remind_start=start, remind_end=end)
    if not hits:
        return (None, [])
    text = semantic.answer_from_hits(hits, query, language=language, tz=tz)
    # De-dupe note ids preserving rank order (a note can contribute several chunks).
    source_ids = list(dict.fromkeys(h["note_id"] for h in hits))
    return (text, source_ids)
