"""
Note lifecycle domain service: capture and on-demand enrichment.

Client-agnostic — used by the Telegram bot today and the public API later. No
client (Telegram) specifics leak in here; callers pass a resolved user_id.
Reminder detection/creation lives in `reminders`; search in `search_service`.
"""

import logging

from services import semantic
import storage
from services import enrichment
from stores import note_store
from stores import chunk_store

logger = logging.getLogger(__name__)


def capture_note(
    user_id: int,
    username: str | None,
    text: str,
    source_type: str = "text",
    audio_bytes: bytes | None = None,
    mime: str | None = None,
) -> int:
    """Persist a note (upload audio if any, chunk + embed). Returns the note id."""
    audio_key = None
    if audio_bytes is not None:
        audio_key = storage.upload_audio(audio_bytes, content_type=mime or "audio/ogg")

    chunks = semantic.build_chunks(text)
    note_id = note_store.save_note(
        user_id, username, text,
        source_type=source_type, audio_key=audio_key, audio_mime=mime,
    )
    chunk_store.save_chunks(note_id, chunks)
    logger.info(
        "Captured note %s (user %s, %s, %d chunk(s))",
        note_id, user_id, source_type, len(chunks),
    )
    return note_id


def enrich_note(user_id: int, note_id: int) -> dict | None:
    """Run the deferred enrichment pass and persist the metadata. Returns the
    metadata dict, or None if the note no longer exists."""
    text = note_store.get_text(note_id)
    if not text:
        logger.warning("enrich_note: note %s not found", note_id)
        return None

    embedding = semantic.embed(text)
    similar = chunk_store.similar_notes(user_id, embedding, exclude_note_id=note_id)
    meta = enrichment.enrich(
        text,
        known_paths=note_store.list_paths(user_id),
        known_tags=note_store.list_tags(user_id),
        similar_notes=similar,
    )
    note_store.set_metadata(
        note_id, meta["type"], meta["title"], meta["priority"],
        meta["tags"], meta["path"],
    )
    logger.info("Enriched note %s -> %s '%s'", note_id, meta["type"], meta["title"])
    return meta


def known_paths(user_id: int) -> list[str]:
    """The user's existing vault paths (controlled vocabulary), most-used first."""
    return note_store.list_paths(user_id)


def set_path(note_id: int, path: str) -> dict | None:
    """Move a note to a different vault path. Returns the note's updated metadata,
    or None if the note doesn't exist."""
    if note_store.get_text(note_id) is None:
        logger.warning("set_path: note %s not found", note_id)
        return None
    note_store.set_path(note_id, path)
    logger.info("Note %s path set to %r", note_id, path)
    return note_store.get_meta(note_id)
