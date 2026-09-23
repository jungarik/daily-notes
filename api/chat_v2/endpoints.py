"""Chat v2 router — POST /api/chat/v2 and /api/chat/v2/confirm.

The same chat tab as `api/chat`, driven by the agent farm instead of the single
conversation agent: the broker picks who runs each hop, an agent that wants a
write pauses the turn, and the responder writes the reply. Both versions are
mounted while v2 is proven; v1 is untouched.

This section owns the thread projection. It loads the thread, hands the data to
the broker, appends what was said to the transcript, stores the turn handle a
later confirm needs, and shapes the response. The broker touches no chat table,
and no agent touches any database the tools do not own.
"""

import logging

from datetime import datetime
from fastapi import APIRouter, Depends

from agents.bootstrap import farm
from api.chat_v2 import db, helper
from api.chat_v2.schemas import ChatConfirmRequest, ChatRequest, ChatResponse
from api.deps import current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat/v2", tags=["chat-v2"])


@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest, user_id: int = Depends(current_user)) -> ChatResponse:
    """Run one turn across the farm. Returns an answer, or — when the user asked
    to act — a write awaiting confirmation."""

    tz, locale = helper.normalize_settings(*db.get_settings(user_id))
    thread = db.get_thread(user_id, req.thread_id) if req.thread_id is not None else None

    if thread is None:
        thread_id, messages = db.create_thread(user_id), []
    else:
        thread_id, messages = thread["id"], list(thread["messages"])

    outcome = farm.start(
        req.message,
        helper.build_context(user_id, datetime.now(tz), tz, locale),
        references={"messages": messages})

    db.save_thread(
        thread_id,
        helper.append_turn(messages, req.message, outcome.reply),
        outcome.pending)
    logger.info(
        "chat v2 turn user=%s thread=%s turn=%s -> %s (%s hops)",
        user_id,
        thread_id,
        outcome.correlation_id,
        outcome.status,
        len(outcome.history))

    return helper.turn_response(thread_id, outcome.status, outcome.reply, outcome.pending)


@router.post("/confirm", response_model=ChatResponse)
def chat_confirm(req: ChatConfirmRequest,
                 user_id: int = Depends(current_user)) -> ChatResponse:
    """Approve or decline the write an agent proposed, then finish the turn."""

    tz, locale = helper.normalize_settings(*db.get_settings(user_id))
    thread = db.get_thread(user_id, req.thread_id)
    pending = helper.find_resumable(thread["pending"]) if thread is not None else None

    if pending is None:
        return helper.nothing_to_confirm(req.thread_id)

    messages = list(thread["messages"])
    outcome = farm.resume(
        pending,
        {"approve": req.approve, "selection": req.selection},
        helper.find_last_user_message(messages),
        helper.build_context(user_id, datetime.now(tz), tz, locale),
        references={"messages": messages})

    db.save_thread(
        req.thread_id,
        helper.append_turn(messages, None, outcome.reply),
        outcome.pending)
    logger.info(
        "chat v2 confirm user=%s thread=%s turn=%s approve=%s -> %s",
        user_id,
        req.thread_id,
        outcome.correlation_id,
        req.approve,
        outcome.status)

    return helper.turn_response(
        req.thread_id, outcome.status, outcome.reply, outcome.pending)
