"""create_reminder enrichment tool."""

import logging
import re
from datetime import datetime

import config
from common import embedings, helper
from agents.contracts import ToolResult
from tools.enrich import db

logger = logging.getLogger(__name__)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…。！？])\s+")


def _atomic_note_text(text: str) -> str:
    value = " ".join(
        line.strip()
        for line in str(text or "").splitlines()
        if line.strip()
    )

    if not value:
        return ""

    sentences = _SENTENCE_SPLIT.split(value)
    value = " ".join(sentences[:config.ATOMIC_NOTE_MAX_SENTENCES]).strip()

    if len(value) <= config.ATOMIC_NOTE_MAX_CHARS:
        return value

    shortened = value[:config.ATOMIC_NOTE_MAX_CHARS].rsplit(" ", 1)[0].strip()

    return shortened.rstrip(" ,.;:-") + "..."


def invoke(context: dict, args: dict) -> ToolResult:
    error = helper.required_values_error(context, "context", ["user_id"])

    if error:
        return ToolResult({"error": error})

    error = helper.required_values_error(args, "args", ["text", "remind_at"])

    if error:
        return ToolResult({"error": error})

    text = (args.get("text") or "").strip()
    raw_time = args.get("remind_at")

    if not text or not raw_time:
        return ToolResult({"error": "Error: text and remind_at are required."})

    remind_at = datetime.fromisoformat(raw_time)
    note_id = args.get("note_id")

    if note_id is None:
        note_text = _atomic_note_text(text)
        note_id = db.save_note(context["user_id"], note_text)
        db.save_chunks(
            note_id,
            embedings.build_chunks(note_text),
        )
        logger.info(
            "Enrich created backing note %s for reminder (user %s)",
            note_id,
            context["user_id"],
        )
    else:
        note_id = int(note_id)

    reminder_id = db.attach_reminder(context["user_id"], note_id, remind_at)

    if reminder_id is None:
        return ToolResult({"error": "Error: referenced note not found."})

    return ToolResult({
        "note_id": note_id,
        "reminder_id": reminder_id,
        "remind_at": remind_at.isoformat(),
    })
