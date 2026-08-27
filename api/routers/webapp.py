"""
Public Web App (Mini App) endpoints.

Unlike /internal (private network + shared token), these are reachable by the
user's browser, so they authenticate with Telegram's signed `initData` instead
of the internal token. The app sends it in the `X-Telegram-Init-Data` header;
we verify it against BOT_TOKEN, resolve the Telegram user to an internal
user_id, and return only that user's data.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, Response

import config
import storage
from api import media_token
from api.telegram_auth import validate_init_data
from services import user_service
from services import note_service
from services import reminders
from agents import chat
from stores import attachment_store
from api.schemas import (
    WebAppNote, WebAppNoteDetail, WebAppGraph,
    WebAppSetPathRequest, WebAppMoveFolderRequest, WebAppMoveFolderResponse,
    ChatRequest, ChatConfirmRequest, ChatResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webapp", tags=["webapp"])


def _with_attachment_urls(detail: dict) -> dict:
    """Rewrite a note detail's attachments to carry a signed proxy URL the browser
    can load (an <img> can't send the initData header, so the URL is the auth).
    The path is relative — the web app is served from the API's own origin."""
    for a in detail.get("attachments", []):
        a["url"] = f"/webapp/attachments/{a['id']}?t={media_token.sign(a['id'])}"
    return detail


def _auth(init_data: str | None) -> int:
    """Validate initData and return the internal user_id (401 if invalid)."""
    user = validate_init_data(
        init_data or "", config.BOT_TOKEN or "",
        config.WEBAPP_INITDATA_MAX_AGE_SECONDS,
    )
    if not user:
        raise HTTPException(status_code=401, detail="invalid init data")
    # In a private chat the Telegram user id equals the chat_id the domain keys on.
    return user_service.resolve(int(user["id"]), user.get("username"))


@router.get("/notes", response_model=list[WebAppNote])
def notes(x_telegram_init_data: str | None = Header(default=None)) -> list[WebAppNote]:
    """The authenticated user's notes for the browser (id, title, path)."""
    user_id = _auth(x_telegram_init_data)
    items = note_service.list_notes_for_user(user_id)
    logger.info("Web app notes for user=%s -> %d", user_id, len(items))
    return [WebAppNote(**it) for it in items]


@router.get("/feed", response_model=list[WebAppNoteDetail])
def feed(x_telegram_init_data: str | None = Header(default=None)) -> list[WebAppNoteDetail]:
    """Full note details for the notes feed (newest first) — each note as a
    complete preview card."""
    user_id = _auth(x_telegram_init_data)
    items = note_service.feed_for_user(user_id)
    logger.info("Web app feed for user=%s -> %d", user_id, len(items))
    return [WebAppNoteDetail(**_with_attachment_urls(it)) for it in items]


@router.get("/attachments/{attachment_id}")
def attachment(attachment_id: int, t: str = "") -> Response:
    """Proxy an attachment's bytes from object storage. Auth is the signed `t`
    token (an <img> can't send headers), so this endpoint is deliberately not
    initData-guarded. The API reaches the bucket even when the browser can't."""
    if not media_token.verify(t, attachment_id):
        raise HTTPException(status_code=403, detail="bad or expired token")
    a = attachment_store.get(attachment_id)
    if a is None:
        raise HTTPException(status_code=404, detail="attachment not found")
    obj = storage.fetch_object(a["storage_key"])
    if obj is None:
        raise HTTPException(status_code=404, detail="attachment unavailable")
    data, content_type = obj
    return Response(
        content=data,
        media_type=content_type or a["mime"] or "application/octet-stream",
        headers={"Cache-Control": f"private, max-age={config.ATTACHMENT_URL_TTL_SECONDS}"},
    )


@router.get("/reminders/count")
def reminders_count(x_telegram_init_data: str | None = Header(default=None)) -> dict:
    """Count of the user's active + future reminders (scheduled/postponed), for
    the web-app header stat."""
    user_id = _auth(x_telegram_init_data)
    return {"count": reminders.active_count(user_id)}


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, x_telegram_init_data: str | None = Header(default=None)) -> ChatResponse:
    """Run one agent turn over the user's notes. Returns either an answer (with
    citations) or a write awaiting confirmation."""
    user_id = _auth(x_telegram_init_data)
    tz, locale = user_service.settings(user_id)
    result = chat.start_turn(user_id, req.message, req.thread_id, datetime.now(tz), tz, locale)
    logger.info("chat turn user=%s thread=%s -> %s", user_id, result["thread_id"], result["status"])
    return ChatResponse(**result)


@router.post("/chat/confirm", response_model=ChatResponse)
def chat_confirm(req: ChatConfirmRequest,
                 x_telegram_init_data: str | None = Header(default=None)) -> ChatResponse:
    """Approve or decline the write the agent paused on, then continue the turn."""
    user_id = _auth(x_telegram_init_data)
    tz, locale = user_service.settings(user_id)
    result = chat.confirm(user_id, req.thread_id, req.approve, datetime.now(tz), tz, locale)
    logger.info("chat confirm user=%s thread=%s approve=%s -> %s",
                user_id, req.thread_id, req.approve, result["status"])
    return ChatResponse(**result)


@router.get("/graph", response_model=WebAppGraph)
def graph(x_telegram_init_data: str | None = Header(default=None)) -> WebAppGraph:
    """The authenticated user's note connection graph (nodes + edges)."""
    user_id = _auth(x_telegram_init_data)
    g = note_service.graph(user_id)
    logger.info("Web app graph for user=%s -> %d nodes / %d edges",
                user_id, len(g["nodes"]), len(g["edges"]))
    return WebAppGraph(**g)


@router.get("/notes/{note_id}", response_model=WebAppNoteDetail)
def note_detail(note_id: int,
                x_telegram_init_data: str | None = Header(default=None)) -> WebAppNoteDetail:
    """One note's full detail for the preview card. 404 if it isn't the user's."""
    user_id = _auth(x_telegram_init_data)
    detail = note_service.web_note_detail(user_id, note_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="note not found")
    return WebAppNoteDetail(**_with_attachment_urls(detail))


@router.post("/notes/{note_id}/path", response_model=WebAppNoteDetail)
def set_note_path(note_id: int, req: WebAppSetPathRequest,
                  x_telegram_init_data: str | None = Header(default=None)) -> WebAppNoteDetail:
    """Rename a single note's full vault path. Returns the updated note detail."""
    user_id = _auth(x_telegram_init_data)
    status, _ = note_service.move_note(user_id, note_id, req.path)
    if status == "invalid":
        raise HTTPException(status_code=422, detail="path must start with a root folder")
    if status == "not_found":
        raise HTTPException(status_code=404, detail="note not found")
    return WebAppNoteDetail(**_with_attachment_urls(note_service.web_note_detail(user_id, note_id)))


@router.post("/folder/move", response_model=WebAppMoveFolderResponse)
def move_folder(req: WebAppMoveFolderRequest,
                x_telegram_init_data: str | None = Header(default=None)) -> WebAppMoveFolderResponse:
    """Bulk-rename a folder: move every note whose path is exactly `old_path` to
    the new path. Returns how many notes were moved."""
    user_id = _auth(x_telegram_init_data)
    status, data = note_service.move_folder(user_id, req.old_path, req.new_path)
    if status == "root":
        raise HTTPException(status_code=400, detail="root folders can't be moved")
    if status == "invalid":
        raise HTTPException(status_code=422, detail="path must start with a root folder")
    return WebAppMoveFolderResponse(count=data["count"], new_path=data["new_path"])
