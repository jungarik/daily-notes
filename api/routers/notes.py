"""
Note endpoints — capture, read (feed/browser/detail/graph), enrich, links, and
media. Everything is user-scoped via `current_user` (browser initData or the
bot's token + X-User-Id); the store is never touched by a client directly.
"""

import logging
import mimetypes
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, File, Form, UploadFile, Response

import config
from stores import file_store
from stores import attachment_store
from services import note_service
from services import reminders
from services import links
from services import transcription
from services import user_service
from api import media_token
from api.deps import current_user
from api.schemas import (
    PathsResponse,
    SetPathRequest,
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
    PolishResponse,
    WebAppNote,
    WebAppNoteDetail,
    WebAppGraph,
    WebAppMoveFolderRequest,
    WebAppMoveFolderResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notes", tags=["notes"])


def _detect_reminder_info(note_id: int, user_id: int, text: str) -> ReminderInfo | None:
    """Run reminder detection for a freshly captured note, resolving the user's
    'now' server-side. Returns the created reminder (id + time) or None."""
    tz, _ = user_service.settings(user_id)
    result = reminders.detect_reminder(note_id, user_id, text, datetime.now(tz))
    if not result:
        return None
    reminder_id, remind_at = result
    return ReminderInfo(id=reminder_id, remind_at=remind_at.isoformat())


def _with_attachment_urls(detail: dict) -> dict:
    """Rewrite a note detail's attachments to carry a signed proxy URL the browser
    can load (an <img> can't send the auth header, so the URL is the auth). The
    path is relative — the Mini App is served from the API's own origin."""
    for a in detail.get("attachments", []):
        a["url"] = f"/api/notes/attachments/{a['id']}?t={media_token.sign(a['id'])}"
    return detail


# ---- capture --------------------------------------------------------------

@router.post("", response_model=CaptureResponse)
def capture(req: CaptureRequest, user_id: int = Depends(current_user)) -> CaptureResponse:
    """Capture a text note (chunk + embed + persist) and, if it's time-bearing,
    create its reminder — the fast capture path, in one round trip. Enrichment is
    deferred (the client's 🧠 Enrich button)."""
    note_id = note_service.capture_note(user_id, req.text)
    reminder = _detect_reminder_info(note_id, user_id, req.text)
    return CaptureResponse(note_id=note_id, text=req.text, reminder=reminder)


@router.post("/voice", response_model=CaptureResponse)
async def capture_voice(
    mime: str | None = Form(None),
    audio: UploadFile = File(...),
    user_id: int = Depends(current_user),
) -> CaptureResponse:
    """Transcribe a voice note, store the audio, then capture it like a text note.
    note_id=None and text="" when nothing usable was heard; 502 if transcription
    itself fails."""
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


def _ext_for(mime: str, filename: str | None) -> str:
    """Pick a file extension from the MIME type (falling back to the uploaded
    filename's suffix), for the storage object key."""
    guessed = mimetypes.guess_extension(mime or "")
    if guessed:
        return guessed.lstrip(".")
    if filename and "." in filename:
        return filename.rsplit(".", 1)[-1].lower()
    return "bin"


@router.post("/media", response_model=CaptureResponse)
async def capture_media(
    text: str = Form(""),
    files: list[UploadFile] = File(...),
    user_id: int = Depends(current_user),
) -> CaptureResponse:
    """Capture a note with up to N image attachments and an optional caption.
    Guardrails: bounded file count, image MIME types only, bounded per-file size."""
    logger.info("capture_media: user=%s files=%d types=%s",
                user_id, len(files), [f.content_type for f in files])
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
        images.append({"bytes": data, "mime": mime, "ext": _ext_for(mime, f.filename)})

    if not images:
        raise HTTPException(status_code=422, detail="no usable files")

    caption = (text or "").strip()
    note_id = note_service.capture_note(user_id, caption, source_type="media", images=images)
    reminder = _detect_reminder_info(note_id, user_id, caption) if caption else None
    return CaptureResponse(note_id=note_id, text=caption, reminder=reminder)


# ---- read (literal paths first, before /{note_id}) ------------------------

@router.get("", response_model=list[WebAppNote])
def list_notes(user_id: int = Depends(current_user)) -> list[WebAppNote]:
    """The user's notes for the browser tree (id, title, path, snippet, links)."""
    return [WebAppNote(**it) for it in note_service.list_notes_for_user(user_id)]


@router.get("/feed", response_model=list[WebAppNoteDetail])
def feed(user_id: int = Depends(current_user)) -> list[WebAppNoteDetail]:
    """Full note cards for the feed (newest first)."""
    items = note_service.feed_for_user(user_id)
    return [WebAppNoteDetail(**_with_attachment_urls(it)) for it in items]


@router.get("/paths", response_model=PathsResponse)
def known_paths(user_id: int = Depends(current_user)) -> PathsResponse:
    """The user's existing vault paths, most-used first."""
    return PathsResponse(paths=note_service.known_paths(user_id))


@router.get("/graph", response_model=WebAppGraph)
def graph(user_id: int = Depends(current_user)) -> WebAppGraph:
    """The user's note connection graph (nodes + edges)."""
    return WebAppGraph(**note_service.graph(user_id))


@router.get("/attachments/{attachment_id}")
def attachment(attachment_id: int, t: str = "") -> Response:
    """Proxy an attachment's bytes from object storage. Auth is the signed `t`
    token (an <img> can't send headers), so this endpoint is deliberately not
    user-guarded. The API reaches the bucket even when the browser can't."""
    if not media_token.verify(t, attachment_id):
        raise HTTPException(status_code=403, detail="bad or expired token")
    a = attachment_store.get(attachment_id)
    if a is None:
        raise HTTPException(status_code=404, detail="attachment not found")
    obj = file_store.fetch_object(a["storage_key"])
    if obj is None:
        raise HTTPException(status_code=404, detail="attachment unavailable")
    data, content_type = obj
    return Response(
        content=data,
        media_type=content_type or a["mime"] or "application/octet-stream",
        headers={"Cache-Control": f"private, max-age={config.ATTACHMENT_URL_TTL_SECONDS}"},
    )


@router.post("/folder/move", response_model=WebAppMoveFolderResponse)
def move_folder(req: WebAppMoveFolderRequest,
                user_id: int = Depends(current_user)) -> WebAppMoveFolderResponse:
    """Bulk-rename a folder: move every note whose path is exactly `old_path`.
    Root folders can't be moved."""
    status, data = note_service.move_folder(user_id, req.old_path, req.new_path)
    if status == "root":
        raise HTTPException(status_code=400, detail="root folders can't be moved")
    if status == "invalid":
        raise HTTPException(status_code=422, detail="path must start with a root folder")
    return WebAppMoveFolderResponse(count=data["count"], new_path=data["new_path"])


@router.get("/{note_id}", response_model=WebAppNoteDetail)
def note_detail(note_id: int, user_id: int = Depends(current_user)) -> WebAppNoteDetail:
    """One note's full detail for the preview card. 404 if it isn't the user's."""
    detail = note_service.web_note_detail(user_id, note_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="note not found")
    return WebAppNoteDetail(**_with_attachment_urls(detail))


# ---- mutate ---------------------------------------------------------------

@router.post("/{note_id}/path", response_model=NoteMeta)
def set_path(note_id: int, req: SetPathRequest,
             user_id: int = Depends(current_user)) -> NoteMeta:
    """Move a note to a different vault path (owner-scoped, validated). The path
    must start with a root folder in any supported language (422 otherwise)."""
    status, meta = note_service.move_note(user_id, note_id, req.path)
    if status == "invalid":
        raise HTTPException(status_code=422, detail="path must start with a root folder")
    if status == "not_found":
        raise HTTPException(status_code=404, detail="note not found")
    return NoteMeta(**meta)


@router.post("/{note_id}/atomize", response_model=AtomizeResponse)
def atomize(note_id: int, user_id: int = Depends(current_user)) -> AtomizeResponse:
    """Split a note into atomic notes, each persisted as a new plain note."""
    created = note_service.atomize_note(user_id, note_id)
    return AtomizeResponse(atoms=[AtomizedNote(**a) for a in created])


@router.post("/{note_id}/delete", response_model=DeleteResponse)
def delete(note_id: int, user_id: int = Depends(current_user)) -> DeleteResponse:
    """Delete a note only if it has no metadata and no links (guarded)."""
    return DeleteResponse(deleted=note_service.delete_bare_note(note_id))


@router.post("/{note_id}/polish", response_model=PolishResponse)
def polish(note_id: int, user_id: int = Depends(current_user)) -> PolishResponse:
    """Clean up a note's wording/punctuation (no invention). 404 if not found."""
    text = note_service.polish_note(note_id)
    if text is None:
        raise HTTPException(status_code=404, detail="note not found")
    return PolishResponse(text=text)


@router.post("/{note_id}/enrich", response_model=NoteMeta)
def enrich(note_id: int, user_id: int = Depends(current_user)) -> NoteMeta:
    """Run the deferred (one-shot) enrichment pass and persist the metadata."""
    meta = note_service.enrich_note(user_id, note_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="note not found")
    return NoteMeta(**meta)


@router.get("/{note_id}/link-candidates", response_model=LinkCandidatesResponse)
def link_candidates(note_id: int, user_id: int = Depends(current_user)) -> LinkCandidatesResponse:
    """Ranked notes to connect this note to, each marked already-linked or not."""
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
def toggle_link(from_note_id: int, to_note_id: int,
                user_id: int = Depends(current_user)) -> ToggleLinkResponse:
    """Connect/disconnect a directed link from → to. Returns the new state."""
    linked = links.toggle_link(from_note_id, to_note_id)
    return ToggleLinkResponse(linked=linked)
