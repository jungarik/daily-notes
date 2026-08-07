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


def _vocabulary(known_projects, known_tags) -> str:
    """A prompt block nudging the model to reuse existing projects/tags."""
    lines = []
    if known_projects:
        lines.append(f"Existing projects: {', '.join(known_projects)}.")
    if known_tags:
        lines.append(f"Existing tags: {', '.join(known_tags)}.")
    if not lines:
        return ""
    return (
        " Reuse an existing project/tag verbatim when it fits; only create a new "
        "one if none of these apply. " + " ".join(lines)
    )


def _similar(similar_notes) -> str:
    """A few-shot block: how similar past notes were classified (for consistency)."""
    if not similar_notes:
        return ""
    lines = [
        f"- \"{n['title']}\" -> type={n['note_type']}, "
        f"projects={n.get('projects') or []}, tags={n.get('tags') or []}"
        for n in similar_notes
    ]
    return (
        " Similar past notes and how they were classified (reuse their type / "
        "projects / tags when appropriate):\n" + "\n".join(lines)
    )


def enrich(text: str, now: datetime, known_projects=None, known_tags=None,
           similar_notes=None) -> dict:
    """Classify + extract metadata for a note. Returns a normalized dict.

    `known_projects`/`known_tags` are the chat's existing vocabulary and
    `similar_notes` are semantically-close already-enriched notes — both keep
    classification consistent instead of drifting.
    """
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
            + _vocabulary(known_projects, known_tags)
            + _similar(similar_notes)
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
