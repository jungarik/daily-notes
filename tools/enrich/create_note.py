"""create_note enrichment tool."""

import logging
import re

import config
from common import embedings, helper
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


def invoke(context: dict, args: dict) -> str:
    error = helper.required_values_error(context, "context", ["user_id"])

    if error:
        return error

    error = helper.required_values_error(args, "args", ["text"])

    if error:
        return error

    text = _atomic_note_text(args.get("text") or "")

    if not text:
        return "Error: text is required."

    note_id = db.save_note(context["user_id"], text)
    db.save_chunks(
        note_id,
        embedings.build_chunks(text),
    )
    logger.info(
        "Enrich agent captured note %s (user %s)",
        note_id,
        context["user_id"],
    )

    return helper.json_text({
        "note_id": note_id,
    })
