"""Enrichment agent orchestration.

`enrich(user_id, note_id, text)` runs the tool-using loop to classify a freshly
captured note, falls back to the proven one-shot enricher if the loop doesn't
converge, then persists the metadata. Client-agnostic; called at capture time.
Never raises — enrichment failing must not lose the note.
"""

import logging

import config
from agents.enrich.tools import Ctx
from agents.enrich.loop import run_loop
from agents.enrich import domain as d

logger = logging.getLogger(__name__)


def _system(root_folders, default_root) -> str:
    return (
        "You organize a person's brain-dump notes (Ukrainian or English) into a "
        "PARA-style vault (Obsidian-style). Classify the note and extract metadata. "
        "You may call list_paths, list_tags and find_similar to stay consistent with "
        "the user's existing vault, then call submit_metadata exactly once with your "
        "final decision. Reuse an existing path/tag verbatim when it fits; extend a "
        "path rather than inventing a parallel one."
        + d.root_folders_block(root_folders, default_root)
    )


def _one_shot(user_id, note_id, text, root_folders, default_root) -> dict:
    """Guaranteed fallback: the existing one-shot enricher with fresh context."""
    embedding = d.embed(text)
    similar = d.similar_notes(
        user_id, embedding, exclude_note_id=note_id, limit=config.ENRICH_SIMILAR_LIMIT)
    return d.enrich(
        text,
        known_paths=d.list_paths(user_id),
        known_tags=d.list_tags(user_id),
        similar_notes=similar,
        root_folders=root_folders,
        default_root_folder=default_root,
    )


def enrich(user_id: int, note_id: int, text: str) -> dict | None:
    """Enrich a note in place (agentic, with a one-shot fallback) and persist the
    metadata. Returns the metadata dict, or None for an empty note."""
    if not (text and text.strip()):
        return None

    root_folders, default_root = d.localized_roots(user_id)
    ctx = Ctx(user_id, note_id, text, d.language(user_id), root_folders, default_root)
    messages = [
        {"role": "system", "content": _system(root_folders, default_root)},
        {"role": "user", "content": text},
    ]

    meta = None
    try:
        meta = run_loop(ctx, messages)
    except Exception:
        logger.exception("enrich agent loop failed for note %s", note_id)

    if meta is None:
        logger.info("enrich agent did not converge for note %s; using one-shot", note_id)
        try:
            meta = _one_shot(user_id, note_id, text, root_folders, default_root)
        except Exception:
            logger.exception("one-shot enrichment failed for note %s", note_id)
            return None

    d.set_metadata(
        note_id, meta["type"], meta["title"], meta["priority"], meta["tags"], meta["path"])
    logger.info("Enriched note %s -> %s '%s' @ %s", note_id, meta["type"], meta["title"], meta["path"])
    return meta
