"""
Public Web App (Mini App) endpoints.

Unlike /internal (private network + shared token), these are reachable by the
user's browser, so they authenticate with Telegram's signed `initData` instead
of the internal token. The app sends it in the `X-Telegram-Init-Data` header;
we verify it against BOT_TOKEN, resolve the Telegram user to an internal
user_id, and return only that user's data.
"""

import logging

from fastapi import APIRouter, Header, HTTPException

import config
from api.telegram_auth import validate_init_data
from services import user_service
from services import note_service
from api.schemas import WebAppNote

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webapp", tags=["webapp"])


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
