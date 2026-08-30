"""Chat router — POST /api/chat and /api/chat/confirm (the Mini App chat tab)."""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.deps import current_user
from api.chat import helper

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatCitation(BaseModel):
    note_id: int
    title: str


class ChatAction(BaseModel):
    name: str
    args: dict = {}
    summary: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: int | None = None


class ChatConfirmRequest(BaseModel):
    thread_id: int
    approve: bool


class ChatResponse(BaseModel):
    thread_id: int
    status: str                       # "answer" | "confirm"
    reply: str | None = None
    action: ChatAction | None = None
    citations: list[ChatCitation] = []


@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest, user_id: int = Depends(current_user)) -> ChatResponse:
    """Run one agent turn over the caller's notes. Returns an answer (with
    citations) or a write awaiting confirmation."""
    result = helper.run_turn(user_id, req.message, req.thread_id)
    logger.info("chat turn user=%s thread=%s -> %s", user_id, result["thread_id"], result["status"])
    return ChatResponse(**result)


@router.post("/confirm", response_model=ChatResponse)
def chat_confirm(req: ChatConfirmRequest,
                 user_id: int = Depends(current_user)) -> ChatResponse:
    """Approve or decline the write the agent paused on, then continue the turn."""
    result = helper.confirm_turn(user_id, req.thread_id, req.approve)
    logger.info("chat confirm user=%s thread=%s approve=%s -> %s",
                user_id, req.thread_id, req.approve, result["status"])
    return ChatResponse(**result)
