"""
Note enrichment: one LLM call that turns a raw brain-dump note into structured
metadata — type, title, projects, tags, priority, and an optional reminder time.

Capture stays frictionless; this is where the intelligence happens. Runs on
every note. On any failure it degrades gracefully to a plain note.
"""

import json
import logging
from datetime import datetime

import config
from openai_client import get_client

logger = logging.getLogger(__name__)

TYPES = ("idea", "task", "reminder", "note", "question", "link")
PRIORITIES = ("low", "med", "high")


def _fallback(text: str) -> dict:
    return {
        "type": "note",
        "title": text.strip()[:80],
        "projects": [],
        "tags": [],
        "priority": "low",
        "reminder_at": None,
    }


def _normalize(data: dict, text: str, now: datetime) -> dict:
    note_type = str(data.get("type", "note")).lower()
    if note_type not in TYPES:
        note_type = "note"

    title = (data.get("title") or text.strip()[:80]).strip() or text.strip()[:80]

    projects = [str(p).strip() for p in (data.get("projects") or []) if str(p).strip()][:3]
    tags = [str(g).strip().lower() for g in (data.get("tags") or []) if str(g).strip()][:5]

    priority = str(data.get("priority", "low")).lower()
    if priority not in PRIORITIES:
        priority = "low"

    remind_at = None
    raw = data.get("reminder_at")
    if raw:
        try:
            dt = datetime.fromisoformat(raw)
            remind_at = dt if dt.tzinfo else dt.replace(tzinfo=now.tzinfo)
        except Exception:
            remind_at = None

    return {
        "type": note_type,
        "title": title,
        "projects": projects,
        "tags": tags,
        "priority": priority,
        "reminder_at": remind_at,
    }


def enrich(text: str, now: datetime) -> dict:
    """Classify + extract metadata for a note. Returns a normalized dict."""
    try:
        system = (
            "You organize a person's brain-dump notes (Ukrainian or English). "
            "Classify the note and extract metadata. Return strict JSON with keys: "
            "type (one of: idea, task, reminder, note, question, link), "
            "title (a concise summary, <=8 words, in the note's own language), "
            "projects (0-2 short kebab-case names of the project/area it belongs to), "
            "tags (0-5 lowercase topic keywords), "
            "priority (one of: low, med, high), "
            "reminder_at (ISO-8601 local time without timezone, or null). "
            f"Current local time is {now.strftime('%Y-%m-%dT%H:%M:%S')} ({now.tzname()}). "
            "Set reminder_at only if the note explicitly asks to be reminded or "
            "scheduled at a time; resolve relative expressions against now; never "
            "invent a time."
        )
        resp = get_client().chat.completions.create(
            model=config.ENRICH_LLM_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
        )
        content = resp.choices[0].message.content
        logger.info("Enrichment | input=%r | response=%s", text, content)
        return _normalize(json.loads(content), text, now)
    except Exception:
        logger.exception("Enrichment failed; storing as a plain note")
        return _fallback(text)
