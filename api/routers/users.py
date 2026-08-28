"""
User identity + settings endpoints (under /api/users).

`resolve` exchanges an external identity (a Telegram chat_id) for the internal
user_id and is the one privileged, pre-identity call — token-guarded, since the
caller has no user_id yet. Everything else is user-scoped via `current_user`.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from services import user_service
from services import reminders
from api.deps import current_user, require_internal_token
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

router = APIRouter(prefix="/api/users", tags=["users"])


@router.post("/resolve", response_model=ResolveUserResponse,
             dependencies=[Depends(require_internal_token)])
def resolve_user(req: ResolveUserRequest) -> ResolveUserResponse:
    """Trusted identity exchange (bot only): chat_id → internal user_id."""
    user_id = user_service.resolve(req.chat_id, req.username)
    return ResolveUserResponse(user_id=user_id)


@router.get("/settings", response_model=UserSettingsResponse)
def get_settings(user_id: int = Depends(current_user)) -> UserSettingsResponse:
    """The caller's raw + effective settings, plus their active reminder count."""
    view = user_service.settings_view(user_id)
    return UserSettingsResponse(active_reminders=reminders.active_count(user_id), **view)


@router.post("/timezone", response_model=SetTimezoneResponse)
def set_timezone(req: SetTimezoneRequest,
                 user_id: int = Depends(current_user)) -> SetTimezoneResponse:
    """Set the caller's timezone. 422 if it isn't a valid IANA name."""
    if not user_service.set_timezone(user_id, req.timezone):
        raise HTTPException(status_code=422, detail="unknown timezone")
    return SetTimezoneResponse(timezone=req.timezone)


@router.post("/language", response_model=SetLanguageResponse)
def set_language(req: SetLanguageRequest,
                 user_id: int = Depends(current_user)) -> SetLanguageResponse:
    """Set the caller's language. 422 if the code isn't supported."""
    lang = user_service.set_language(user_id, req.language)
    if lang is None:
        raise HTTPException(status_code=422, detail="unsupported language")
    return SetLanguageResponse(language=lang)
