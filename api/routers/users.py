"""
User identity endpoints.

Exchange an external client identity (a Telegram chat_id) for the internal
user_id the domain keys on. This is how a thin client — which must not touch the
database — obtains the user_id it then passes to every other endpoint (search,
capture, ...). The mapping is stable, so clients should cache it per session.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from services import user_service
from services import reminders
from api.deps import require_internal_token
from api.schemas import (
    ResolveUserRequest,
    ResolveUserResponse,
    UserSettingsResponse,
    SetTimezoneRequest,
    SetTimezoneResponse,
    SetLanguageRequest,
    SetLanguageResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal/users",
    tags=["users"],
    dependencies=[Depends(require_internal_token)],
)


@router.post("/resolve", response_model=ResolveUserResponse)
def resolve_user(req: ResolveUserRequest) -> ResolveUserResponse:
    user_id = user_service.resolve(req.chat_id)
    return ResolveUserResponse(user_id=user_id)


@router.get("/settings", response_model=UserSettingsResponse)
def get_settings(user_id: int) -> UserSettingsResponse:
    """A user's raw + effective settings, plus their active reminder count — the
    per-user context a client needs to format replies (timezone, language, /user)."""
    view = user_service.settings_view(user_id)
    return UserSettingsResponse(
        active_reminders=reminders.active_count(user_id), **view
    )


@router.post("/timezone", response_model=SetTimezoneResponse)
def set_timezone(req: SetTimezoneRequest) -> SetTimezoneResponse:
    """Set a user's timezone. 422 if it isn't a valid IANA name."""
    if not user_service.set_timezone(req.user_id, req.timezone):
        raise HTTPException(status_code=422, detail="unknown timezone")
    return SetTimezoneResponse(timezone=req.timezone)


@router.post("/language", response_model=SetLanguageResponse)
def set_language(req: SetLanguageRequest) -> SetLanguageResponse:
    """Set a user's language. 422 if the code isn't supported."""
    lang = user_service.set_language(req.user_id, req.language)
    if lang is None:
        raise HTTPException(status_code=422, detail="unsupported language")
    return SetLanguageResponse(language=lang)
