"""
Agentic chat endpoints (under /api) — the Mini App's chat tab. User-scoped via
`current_user`; the agent runs server-side over the caller's own notes.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends

from services import user_service
from agents import chat as chat_agent
from api.deps import current_user
from api.schemas import ChatRequest, ChatConfirmRequest, ChatResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, user_id: int = Depends(current_user)) -> ChatResponse:
    """Run one agent turn over the caller's notes. Returns an answer (with
    citations) or a write awaiting confirmation."""
    tz, locale = user_service.settings(user_id)
    result = chat_agent.start_turn(user_id, req.message, req.thread_id, datetime.now(tz), tz, locale)
    logger.info("chat turn user=%s thread=%s -> %s", user_id, result["thread_id"], result["status"])
    return ChatResponse(**result)


@router.post("/chat/confirm", response_model=ChatResponse)
def chat_confirm(req: ChatConfirmRequest,
                 user_id: int = Depends(current_user)) -> ChatResponse:
    """Approve or decline the write the agent paused on, then continue the turn."""
    tz, locale = user_service.settings(user_id)
    result = chat_agent.confirm(user_id, req.thread_id, req.approve, datetime.now(tz), tz, locale)
    logger.info("chat confirm user=%s thread=%s approve=%s -> %s",
                user_id, req.thread_id, req.approve, result["status"])
    return ChatResponse(**result)
