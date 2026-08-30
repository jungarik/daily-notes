"""Telegram-bot router — the full bot-facing surface under /api/telegram_bot.

Merges what were the notes (capture + mutate), reminders, users, search and ping
routers, re-prefixed. User-scoped routes use `current_user`; the cross-user
dispatcher plumbing + identity resolve are token-only (`require_internal_token`).
Response/request models are section-local.
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, File, Form, UploadFile

import config
from api.deps import current_user, require_internal_token
from api.telegram_bot import helper
from api.telegram_bot.schemas import (
    ReminderInfo, CaptureRequest, CaptureResponse, PathsResponse, SetPathRequest,
    NoteMeta, AtomizedNote, AtomizeResponse, DeleteResponse, PolishResponse,
    LinkCandidate, LinkCandidatesResponse, ToggleLinkResponse, ReminderItem,
    RemindersResponse, CountResponse, SnoozeRequest, SnoozeResponse,
    ReminderActionResponse, ClaimDueRequest, ClaimedReminder, ClaimDueResponse,
    ResolveUserRequest, ResolveUserResponse, UserSettingsResponse,
    SetTimezoneRequest, SetTimezoneResponse, SetLanguageRequest,
    SetLanguageResponse, SearchRequest, SearchResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/telegram_bot", tags=["telegram_bot"])


# ---- capture --------------------------------------------------------------

@router.post("/notes", response_model=CaptureResponse)
def capture(req: CaptureRequest, user_id: int = Depends(current_user)) -> CaptureResponse:
    """Capture a text note (chunk + embed + persist) and, if time-bearing, its
    reminder — the fast path. Enrichment is deferred (the 🧠 Enrich button)."""
    note_id = helper.capture_note(user_id, req.text)
    reminder = helper.detect_reminder_info(note_id, user_id, req.text)
    return CaptureResponse(note_id=note_id, text=req.text,
                           reminder=ReminderInfo(**reminder) if reminder else None)


@router.post("/notes/voice", response_model=CaptureResponse)
async def capture_voice(
    mime: str | None = Form(None),
    audio: UploadFile = File(...),
    user_id: int = Depends(current_user),
) -> CaptureResponse:
    """Transcribe a voice note, store the audio, capture it like a text note.
    note_id=None, text='' when nothing usable was heard; 502 on transcription fail."""
    audio_bytes = await audio.read()
    try:
        text = helper.transcribe(audio_bytes)
    except Exception:
        logger.exception("Transcription failed")
        raise HTTPException(status_code=502, detail="transcription_failed")
    if not text:
        return CaptureResponse(note_id=None, text="", reminder=None)
    note_id = helper.capture_note(
        user_id, text,
        source_type="voice", audio_bytes=audio_bytes, mime=mime or "audio/ogg",
    )
    reminder = helper.detect_reminder_info(note_id, user_id, text)
    return CaptureResponse(note_id=note_id, text=text,
                           reminder=ReminderInfo(**reminder) if reminder else None)


@router.post("/notes/media", response_model=CaptureResponse)
async def capture_media(
    text: str = Form(""),
    files: list[UploadFile] = File(...),
    user_id: int = Depends(current_user),
) -> CaptureResponse:
    """Capture a note with up to N image attachments and an optional caption.
    Guardrails: bounded count, image MIME only, bounded per-file size."""
    if not files:
        raise HTTPException(status_code=422, detail="no files")
    if len(files) > config.ATTACHMENT_MAX_COUNT:
        raise HTTPException(status_code=422, detail=f"too many files (max {config.ATTACHMENT_MAX_COUNT})")

    images: list[dict] = []
    for f in files:
        mime = (f.content_type or "").lower()
        if mime not in config.ATTACHMENT_IMAGE_MIME:
            raise HTTPException(status_code=415, detail=f"unsupported media type: {mime or 'unknown'}")
        data = await f.read()
        if not data:
            continue
        if len(data) > config.ATTACHMENT_MAX_BYTES:
            raise HTTPException(status_code=413, detail=f"file too large (max {config.ATTACHMENT_MAX_BYTES} bytes)")
        images.append({"bytes": data, "mime": mime, "ext": helper.ext_for(mime, f.filename)})

    if not images:
        raise HTTPException(status_code=422, detail="no usable files")

    caption = (text or "").strip()
    note_id = helper.capture_note(user_id, caption, source_type="media", images=images)
    reminder = helper.detect_reminder_info(note_id, user_id, caption) if caption else None
    return CaptureResponse(note_id=note_id, text=caption,
                           reminder=ReminderInfo(**reminder) if reminder else None)


# ---- read / mutate --------------------------------------------------------

@router.get("/notes/paths", response_model=PathsResponse)
def known_paths(user_id: int = Depends(current_user)) -> PathsResponse:
    """The user's existing vault paths, most-used first."""
    return PathsResponse(paths=helper.known_paths(user_id))


@router.post("/notes/{note_id}/path", response_model=NoteMeta)
def set_path(note_id: int, req: SetPathRequest,
             user_id: int = Depends(current_user)) -> NoteMeta:
    """Move a note to a different vault path (owner-scoped, validated)."""
    status, meta = helper.move_note(user_id, note_id, req.path)
    if status == "invalid":
        raise HTTPException(status_code=422, detail="path must start with a root folder")
    if status == "not_found":
        raise HTTPException(status_code=404, detail="note not found")
    return NoteMeta(**meta)


@router.post("/notes/{note_id}/atomize", response_model=AtomizeResponse)
def atomize(note_id: int, user_id: int = Depends(current_user)) -> AtomizeResponse:
    """Split a note into atomic notes, each persisted as a new plain note."""
    created = helper.atomize_note(user_id, note_id)
    return AtomizeResponse(atoms=[AtomizedNote(**a) for a in created])


@router.post("/notes/{note_id}/delete", response_model=DeleteResponse)
def delete(note_id: int, user_id: int = Depends(current_user)) -> DeleteResponse:
    """Delete a note only if it has no metadata and no links (guarded)."""
    return DeleteResponse(deleted=helper.delete_bare_note(note_id))


@router.post("/notes/{note_id}/polish", response_model=PolishResponse)
def polish(note_id: int, user_id: int = Depends(current_user)) -> PolishResponse:
    """Clean up a note's wording/punctuation (no invention). 404 if not found."""
    text = helper.polish_note(note_id)
    if text is None:
        raise HTTPException(status_code=404, detail="note not found")
    return PolishResponse(text=text)


@router.post("/notes/{note_id}/enrich", response_model=NoteMeta)
def enrich(note_id: int, user_id: int = Depends(current_user)) -> NoteMeta:
    """Run the deferred (one-shot) enrichment pass and persist the metadata."""
    meta = helper.enrich_note(user_id, note_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="note not found")
    return NoteMeta(**meta)


@router.get("/notes/{note_id}/link-candidates", response_model=LinkCandidatesResponse)
def link_candidates(note_id: int, user_id: int = Depends(current_user)) -> LinkCandidatesResponse:
    """Ranked notes to connect this note to, each marked already-linked or not."""
    cands = helper.link_candidates(user_id, note_id)
    return LinkCandidatesResponse(candidates=[
        LinkCandidate(
            note_id=c["note_id"], title=c.get("title"), path=c.get("path"),
            tags=c.get("tags") or [], score=c.get("score"),
            linked=helper.is_linked(note_id, c["note_id"]),
        )
        for c in cands
    ])


@router.post("/notes/{from_note_id}/links/{to_note_id}/toggle", response_model=ToggleLinkResponse)
def toggle_link(from_note_id: int, to_note_id: int,
                user_id: int = Depends(current_user)) -> ToggleLinkResponse:
    """Connect/disconnect a directed link from → to. Returns the new state."""
    return ToggleLinkResponse(linked=helper.toggle_link(from_note_id, to_note_id))


# ---- reminders ------------------------------------------------------------

@router.get("/reminders", response_model=RemindersResponse)
def list_reminders(user_id: int = Depends(current_user)) -> RemindersResponse:
    """The caller's upcoming (scheduled/postponed) reminders, soonest first."""
    rows = helper.upcoming(user_id)
    return RemindersResponse(reminders=[
        ReminderItem(id=_id, remind_at=remind_at.isoformat(), text=text, status=status)
        for (_id, remind_at, text, status) in rows
    ])


@router.get("/reminders/count", response_model=CountResponse)
def count(user_id: int = Depends(current_user)) -> CountResponse:
    """How many active reminders the caller has."""
    return CountResponse(count=helper.active_count(user_id))


@router.post("/reminders/{reminder_id}/snooze", response_model=SnoozeResponse)
def snooze(reminder_id: int, req: SnoozeRequest,
           user_id: int = Depends(current_user)) -> SnoozeResponse:
    """Postpone a reminder; the new time is resolved from the caller's timezone."""
    if req.mode != "tomorrow" and not req.mode.isdigit():
        raise HTTPException(status_code=422, detail="mode must be 'tomorrow' or minutes")
    new_time = helper.snooze(reminder_id, user_id, req.mode)
    return SnoozeResponse(remind_at=new_time.isoformat())


@router.post("/reminders/claim-due", response_model=ClaimDueResponse,
             dependencies=[Depends(require_internal_token)])
def claim_due(req: ClaimDueRequest) -> ClaimDueResponse:
    """Atomically claim due reminders for delivery (the bot's poll loop)."""
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=config.SENDING_STALE_SECONDS)
    rows = helper.claim_due(now, stale_before, req.limit)
    return ClaimDueResponse(reminders=[
        ClaimedReminder(
            reminder_id=_id, user_id=uid, chat_id=chat_id,
            remind_at=remind_at.isoformat(), text=text,
            locale=helper.language(uid),
        )
        for (_id, uid, chat_id, text, remind_at) in rows
    ])


@router.post("/reminders/{reminder_id}/retry", response_model=ReminderActionResponse,
             dependencies=[Depends(require_internal_token)])
def retry(reminder_id: int) -> ReminderActionResponse:
    helper.reschedule(reminder_id)
    return ReminderActionResponse(ok=True)


@router.post("/reminders/{reminder_id}/cancel", response_model=ReminderActionResponse,
             dependencies=[Depends(require_internal_token)])
def cancel(reminder_id: int) -> ReminderActionResponse:
    helper.cancel(reminder_id)
    return ReminderActionResponse(ok=True)


@router.post("/reminders/{reminder_id}/done", response_model=ReminderActionResponse,
             dependencies=[Depends(require_internal_token)])
def done(reminder_id: int) -> ReminderActionResponse:
    helper.mark_done(reminder_id)
    return ReminderActionResponse(ok=True)


# ---- users ----------------------------------------------------------------

@router.post("/users/resolve", response_model=ResolveUserResponse,
             dependencies=[Depends(require_internal_token)])
def resolve_user(req: ResolveUserRequest) -> ResolveUserResponse:
    """Trusted identity exchange (bot only): chat_id → internal user_id."""
    return ResolveUserResponse(user_id=helper.resolve(req.chat_id, req.username))


@router.get("/users/settings", response_model=UserSettingsResponse)
def get_settings(user_id: int = Depends(current_user)) -> UserSettingsResponse:
    """The caller's raw + effective settings, plus their active reminder count."""
    view = helper.settings_view(user_id)
    return UserSettingsResponse(active_reminders=helper.active_count(user_id), **view)


@router.post("/users/timezone", response_model=SetTimezoneResponse)
def set_timezone(req: SetTimezoneRequest,
                 user_id: int = Depends(current_user)) -> SetTimezoneResponse:
    """Set the caller's timezone. 422 if it isn't a valid IANA name."""
    if not helper.set_timezone(user_id, req.timezone):
        raise HTTPException(status_code=422, detail="unknown timezone")
    return SetTimezoneResponse(timezone=req.timezone)


@router.post("/users/language", response_model=SetLanguageResponse)
def set_language(req: SetLanguageRequest,
                 user_id: int = Depends(current_user)) -> SetLanguageResponse:
    """Set the caller's language. 422 if the code isn't supported."""
    lang = helper.set_language(user_id, req.language)
    if lang is None:
        raise HTTPException(status_code=422, detail="unsupported language")
    return SetLanguageResponse(language=lang)


# ---- search / meta --------------------------------------------------------

@router.post("/search", response_model=SearchResponse)
def search(req: SearchRequest, user_id: int = Depends(current_user)) -> SearchResponse:
    """Agenda-aware RAG answer over the caller's notes."""
    tz, language = helper.settings(user_id)
    answer = helper.search_answer(user_id, req.query, datetime.now(tz), language=language, tz=tz)
    return SearchResponse(answer=answer)


@router.get("/ping", dependencies=[Depends(require_internal_token)])
def ping():
    """Connectivity + auth probe for the bot at startup."""
    return {"pong": True}
