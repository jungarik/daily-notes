"""
Note endpoints.

Currently: the user's known vault paths (controlled vocabulary) and moving a
note to a different path. Both go through `note_service`; the store is never
touched by a client directly.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, File, Form, UploadFile

import config
from services import note_service
from services import reminders
from services import links
from services import transcription
from services import user_service
from api.deps import require_internal_token
from api.schemas import (
    PathsResponse,
    SetPathRequest,
    EnrichRequest,
    NoteMeta,
    CaptureRequest,
    CaptureResponse,
    ReminderInfo,
    LinkCandidate,
    LinkCandidatesResponse,
    ToggleLinkResponse,
    AtomizedNote,
    AtomizeResponse,
    DeleteResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal/notes",
    tags=["notes"],
    dependencies=[Depends(require_internal_token)],
)


def _detect_reminder_info(note_id: int, user_id: int, text: str) -> ReminderInfo | None:
    """Run reminder detection for a freshly captured note, resolving the user's
    'now' server-side. Returns the created reminder (id + time) or None."""
    tz, _ = user_service.settings(user_id)
    result = reminders.detect_reminder(note_id, user_id, text, datetime.now(tz))
    if not result:
        return None
    reminder_id, remind_at = result
    return ReminderInfo(id=reminder_id, remind_at=remind_at.isoformat())


@router.post("", response_model=CaptureResponse)
def capture(req: CaptureRequest) -> CaptureResponse:
    """Capture a text note (chunk + embed + persist) and, if it's time-bearing,
    create its reminder — the fast capture path, in one round trip."""
    note_id = note_service.capture_note(req.user_id, req.text)
    reminder = _detect_reminder_info(note_id, req.user_id, req.text)
    return CaptureResponse(note_id=note_id, text=req.text, reminder=reminder)


@router.post("/voice", response_model=CaptureResponse)
async def capture_voice(
    user_id: int = Form(...),
    mime: str | None = Form(None),
    audio: UploadFile = File(...),
) -> CaptureResponse:
    """Transcribe a voice note, store the audio, then capture it like a text note.

    Returns note_id=None and text="" when nothing usable was heard; 502 if the
    transcription backend itself fails (so the client can distinguish the two).
    """
    audio_bytes = await audio.read()
    try:
        text = transcription.transcribe(audio_bytes)
    except Exception:
        logger.exception("Transcription failed")
        raise HTTPException(status_code=502, detail="transcription_failed")
    if not text:
        return CaptureResponse(note_id=None, text="", reminder=None)

    note_id = note_service.capture_note(
        user_id, text,
        source_type="voice", audio_bytes=audio_bytes, mime=mime or "audio/ogg",
    )
    reminder = _detect_reminder_info(note_id, user_id, text)
    return CaptureResponse(note_id=note_id, text=text, reminder=reminder)


@router.post("/{note_id}/atomize", response_model=AtomizeResponse)
def atomize(note_id: int, req: EnrichRequest) -> AtomizeResponse:
    """Split a note into atomic notes, each persisted as a new plain note. Returns
    the created atoms; empty when the note was already a single idea."""
    created = note_service.atomize_note(req.user_id, note_id)
    return AtomizeResponse(atoms=[AtomizedNote(**a) for a in created])


@router.post("/{note_id}/delete", response_model=DeleteResponse)
def delete(note_id: int) -> DeleteResponse:
    """Delete a note only if it has no metadata and no links (guarded). `deleted`
    is False when the guard blocked it."""
    return DeleteResponse(deleted=note_service.delete_bare_note(note_id))


@router.get("/{note_id}/link-candidates", response_model=LinkCandidatesResponse)
def link_candidates(note_id: int, user_id: int) -> LinkCandidatesResponse:
    """Ranked notes to connect this note to, each marked with whether it's already
    linked (so the client renders the ✅/◻️ picker without extra calls)."""
    cands = links.candidates(user_id, note_id)
    return LinkCandidatesResponse(candidates=[
        LinkCandidate(
            note_id=c["note_id"], title=c.get("title"), path=c.get("path"),
            tags=c.get("tags") or [], score=c.get("score"),
            linked=links.is_linked(note_id, c["note_id"]),
        )
        for c in cands
    ])


@router.post("/{from_note_id}/links/{to_note_id}/toggle", response_model=ToggleLinkResponse)
def toggle_link(from_note_id: int, to_note_id: int) -> ToggleLinkResponse:
    """Connect/disconnect a directed link from → to. Returns the new state."""
    linked = links.toggle_link(from_note_id, to_note_id)
    return ToggleLinkResponse(linked=linked)


@router.get("/paths", response_model=PathsResponse)
def known_paths(user_id: int) -> PathsResponse:
    """The user's existing vault paths, most-used first."""
    return PathsResponse(paths=note_service.known_paths(user_id))


@router.post("/{note_id}/enrich", response_model=NoteMeta)
def enrich(note_id: int, req: EnrichRequest) -> NoteMeta:
    """Run the deferred enrichment pass and persist the metadata (type/title/path/
    tags/priority). 404 if the note no longer exists."""
    meta = note_service.enrich_note(req.user_id, note_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="note not found")
    return NoteMeta(**meta)


@router.post("/{note_id}/path", response_model=NoteMeta)
def set_path(note_id: int, req: SetPathRequest) -> NoteMeta:
    """Move a note to a different vault path; returns the note's updated metadata.

    The path must start with a root folder (422 otherwise); it's canonicalized
    before saving so casing matches config.ROOT_FOLDERS.
    """
    cleaned = note_service.clean_root_path(req.path)
    if cleaned is None:
        raise HTTPException(
            status_code=422,
            detail="Path must start with a root folder: " + ", ".join(config.ROOT_FOLDERS),
        )
    meta = note_service.set_path(note_id, cleaned)
    if meta is None:
        raise HTTPException(status_code=404, detail="note not found")
    return NoteMeta(**meta)
