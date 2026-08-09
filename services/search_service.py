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
