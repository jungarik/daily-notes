"""Chat router — POST /api/chat and /api/chat/confirm (the Mini App chat tab).

This section owns the thread projection: it loads the thread, hands the data to
the conversation agent, persists the result the agent returns, and shapes the
response. The agent itself touches no database.
"""

import logging

from datetime import datetime
from fastapi import APIRouter, Depends

from api.deps import current_user
from api.chat import db, helper
from api.chat.schemas import ChatRequest, ChatConfirmRequest, ChatResponse
from agents import conversation as chat_agent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest, user_id: int = Depends(current_user)) -> ChatResponse:
    """Run one agent turn over the caller's notes. Returns an answer (with
    citations) or — when the user asked to act — a write awaiting confirmation
    (proposed by the enrich agent)."""

    tz, locale = helper.normalize_settings(*db.get_settings(user_id))
    thread = db.get_thread(user_id, req.thread_id) if req.thread_id is not None else None

    if thread is None:
        thread_id, messages, pending = db.create_thread(user_id), [], None
    else:
        thread_id, messages, pending = (
            thread["id"],
            list(thread["messages"]),
            thread.get("pending"),
        )

    result = chat_agent.run_turn(
        thread_id,
        messages,
        pending,
        req.message,
        user_id,
        datetime.now(tz),
        tz,
        locale,
    )

    db.save_thread(thread_id, result.get("messages") or [], result.get("pending"))
    logger.info(
        "chat turn user=%s thread=%s -> %s",
        user_id,
        thread_id,
        result["status"])

    return helper.turn_response(thread_id, result)


@router.post("/confirm", response_model=ChatResponse)
def chat_confirm(req: ChatConfirmRequest,
                 user_id: int = Depends(current_user)) -> ChatResponse:
    """Approve or decline the action the agent handed off, then continue the turn."""

    tz, locale = helper.normalize_settings(*db.get_settings(user_id))
    thread = db.get_thread(user_id, req.thread_id)

    if thread is None:
        return helper.nothing_to_confirm(req.thread_id)

    result = chat_agent.run_confirmation(
        req.thread_id,
        list(thread["messages"]),
        thread.get("pending"),
        req.approve,
        req.selection,
        user_id,
        datetime.now(tz),
        tz,
        locale,
    )

    if result is None:
        return helper.nothing_to_confirm(req.thread_id)

    db.save_thread(req.thread_id, result.get("messages") or [], result.get("pending"))
    logger.info(
        "chat confirm user=%s thread=%s approve=%s -> %s",
        user_id,
        req.thread_id,
        req.approve,
        result["status"])

    return helper.turn_response(req.thread_id, result)
