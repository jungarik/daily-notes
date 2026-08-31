"""Chat router — POST /api/chat and /api/chat/confirm (the Mini App chat tab)."""

import logging

from fastapi import APIRouter, Depends

from api.deps import current_user
from api.chat import helper
from api.chat.schemas import ChatRequest, ChatConfirmRequest, ChatResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest, user_id: int = Depends(current_user)) -> ChatResponse:
    """Run one agent turn over the caller's notes. Returns an answer (with
    citations) or — when the user asked to act — a write awaiting confirmation
    (proposed by the enrich agent)."""
    result = helper.run_turn(user_id, req.message, req.thread_id)
    logger.info("chat turn user=%s thread=%s -> %s", user_id, result["thread_id"], result["status"])
    return ChatResponse(**result)


@router.post("/confirm", response_model=ChatResponse)
def chat_confirm(req: ChatConfirmRequest,
                 user_id: int = Depends(current_user)) -> ChatResponse:
    """Approve or decline the action the agent handed off, then continue the turn."""
    result = helper.confirm_turn(user_id, req.thread_id, req.approve)
    logger.info("chat confirm user=%s thread=%s approve=%s -> %s",
                user_id, req.thread_id, req.approve, result["status"])
    return ChatResponse(**result)
