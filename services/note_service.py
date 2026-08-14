"""
Note lifecycle domain service: capture and on-demand enrichment.

Client-agnostic — used by the Telegram bot today and the public API later. No
client (Telegram) specifics leak in here; callers pass a resolved user_id.
Reminder detection/creation lives in `reminders`; search in `search_service`.
"""

import logging

import config
from services import semantic
from services import atomize
import storage
from services import enrichment
from stores import note_store
from stores import chunk_store

logger = logging.getLogger(__name__)


def capture_note(
    user_id: int,
    text: str,
    source_type: str = "text",
    audio_bytes: bytes | None = None,
    mime: str | None = None,
) -> int:
    """Persist a note (upload audio if any, chunk + embed). Returns the note id.

    The sender's username is stored on the user, not the note, so it isn't passed
    here.
    """
    audio_key = None
    if audio_bytes is not None:
        audio_key = storage.upload_audio(audio_bytes, content_type=mime or "audio/ogg")

    chunks = semantic.build_chunks(text)
    note_id = note_store.save_note(
        user_id, text,
        source_type=source_type, audio_key=audio_key, audio_mime=mime,
    )
    chunk_store.save_chunks(note_id, chunks)
    logger.info(
        "Captured note %s (user %s, %s, %d chunk(s))",
        note_id, user_id, source_type, len(chunks),
    )
    return note_id


def atomize_note(user_id: int, note_id: int) -> list[dict]:
    """Split a note into atomic notes, persisting each as a new (plain) note.

    Returns [{note_id, text}] for the created atoms, or [] when the note is
    already a single idea (nothing is created). Atoms are plain notes — no
    metadata, no links — so each can be enriched, atomized again, or cancelled
    independently.
    """
    text = note_store.get_text(note_id)
    if not text:
        logger.warning("atomize_note: note %s not found", note_id)
        return []
    atoms = atomize.split(text)
    if len(atoms) < 2:
        logger.info("Note %s is already atomic; nothing split", note_id)
        return []
    created = [{"note_id": capture_note(user_id, atom), "text": atom} for atom in atoms]
    logger.info("Atomized note %s into %d note(s)", note_id, len(created))
    return created


def delete_bare_note(note_id: int) -> bool:
    """Delete a note only if it has no metadata and no links (guarded, to protect
    enriched/linked notes from an accidental Cancel). Returns True if deleted."""
    deleted = note_store.delete_if_bare(note_id)
    logger.info(
        "Delete note %s: %s", note_id,
        "deleted" if deleted else "blocked (has metadata or links)",
    )
    return deleted


def enrich_note(user_id: int, note_id: int) -> dict | None:
    """Run the deferred enrichment pass and persist the metadata. Returns the
    metadata dict, or None if the note no longer exists."""
    text = note_store.get_text(note_id)
    if not text:
        logger.warning("enrich_note: note %s not found", note_id)
        return None

    embedding = semantic.embed(text)
    similar = chunk_store.similar_notes(
        user_id, embedding, exclude_note_id=note_id,
        limit=config.ENRICH_SIMILAR_LIMIT,
    )
    meta = enrichment.enrich(
        text,
        known_paths=note_store.list_paths(user_id),
        known_tags=note_store.list_tags(user_id),
        similar_notes=similar,
        root_folders=config.ROOT_FOLDERS,
        default_root_folder=config.DEFAULT_ROOT_FOLDER,
    )
    note_store.set_metadata(
        note_id, meta["type"], meta["title"], meta["priority"],
        meta["tags"], meta["path"],
    )
    logger.info("Enriched note %s -> %s '%s'", note_id, meta["type"], meta["title"])
    return meta


def known_paths(user_id: int) -> list[str]:
    """The path vocabulary offered to the user/model: their existing DB paths
    (most-used first), then any predefined default folders not already present."""
    paths = [name for name, _ in note_store.list_paths(user_id)]
    return paths


def clean_root_path(path: str) -> str | None:
    """Normalize a user-entered path and require it to start with a root folder.

    Returns the canonical path (root folder cased as in config.ROOT_FOLDERS), or
    None if it's empty or doesn't start with a known root folder.
    """
    if not path:
        return None
    parts = [p.strip() for p in str(path).replace("\\", "/").split("/")]
    parts = [p for p in parts if p and p not in (".", "..")]
    if not parts:
        return None
    roots = {name.lower(): name for name in config.ROOT_FOLDERS}
    canonical = roots.get(parts[0].lower())
    if canonical is None:
        return None
    return "/".join([canonical] + parts[1:])


def set_path(note_id: int, path: str) -> dict | None:
    """Move a note to a different vault path. Returns the note's updated metadata,
    or None if the note doesn't exist."""
    if note_store.get_text(note_id) is None:
        logger.warning("set_path: note %s not found", note_id)
        return None
    note_store.set_path(note_id, path)
    logger.info("Note %s path set to %r", note_id, path)
    return note_store.get_meta(note_id)
