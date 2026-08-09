"""
User identity endpoints.

Exchange an external client identity (a Telegram chat_id) for the internal
user_id the domain keys on. This is how a thin client — which must not touch the
database — obtains the user_id it then passes to every other endpoint (search,
capture, ...). The mapping is stable, so clients should cache it per session.
"""

import logging

from fastapi import APIRouter, Depends

from services import user_service
from api.deps import require_internal_token
from api.schemas import ResolveUserRequest, ResolveUserResponse

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
