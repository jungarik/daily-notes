"""
Reminder endpoints (under /api/reminders).

User-scoped reads/actions (list, count, snooze) go through `current_user`; the
cross-user dispatcher plumbing (claim-due, retry/cancel/done) is token-only —
the bot's delivery loop, which no browser should reach.
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

import config
from services import reminders
from services import user_service
from api.deps import current_user, require_internal_token
from api.schemas import (
    ReminderActionResponse,
    SnoozeRequest,
    SnoozeResponse,
    RemindersResponse,
    ReminderItem,
    CountResponse,
    ClaimDueRequest,
    ClaimedReminder,
    ClaimDueResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reminders", tags=["reminders"])


@router.get("", response_model=RemindersResponse)
def list_reminders(user_id: int = Depends(current_user)) -> RemindersResponse:
    """The caller's upcoming (scheduled/postponed) reminders, soonest first."""
    rows = reminders.upcoming(user_id)
    return RemindersResponse(reminders=[
        ReminderItem(id=_id, remind_at=remind_at.isoformat(), text=text, status=status)
        for (_id, remind_at, text, status) in rows
    ])


@router.get("/count", response_model=CountResponse)
def count(user_id: int = Depends(current_user)) -> CountResponse:
    """How many active reminders the caller has."""
    return CountResponse(count=reminders.active_count(user_id))


@router.post("/{reminder_id}/snooze", response_model=SnoozeResponse)
def snooze(reminder_id: int, req: SnoozeRequest,
           user_id: int = Depends(current_user)) -> SnoozeResponse:
    """Postpone a reminder; the new time is resolved from the caller's timezone."""
    if req.mode != "tomorrow" and not req.mode.isdigit():
        raise HTTPException(status_code=422, detail="mode must be 'tomorrow' or minutes")
    new_time = reminders.snooze(reminder_id, user_id, req.mode)
    return SnoozeResponse(remind_at=new_time.isoformat())


# ---- dispatcher plumbing (token-only, cross-user) -------------------------

@router.post("/claim-due", response_model=ClaimDueResponse,
             dependencies=[Depends(require_internal_token)])
def claim_due(req: ClaimDueRequest) -> ClaimDueResponse:
    """Atomically claim due reminders for delivery (the bot's poll loop)."""
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=config.SENDING_STALE_SECONDS)
    rows = reminders.claim_due(now, stale_before, req.limit)
    return ClaimDueResponse(reminders=[
        ClaimedReminder(
            reminder_id=_id, user_id=uid, chat_id=chat_id,
            remind_at=remind_at.isoformat(), text=text,
            locale=user_service.language(uid),
        )
        for (_id, uid, chat_id, text, remind_at) in rows
    ])


@router.post("/{reminder_id}/retry", response_model=ReminderActionResponse,
             dependencies=[Depends(require_internal_token)])
def retry(reminder_id: int) -> ReminderActionResponse:
    """Return a claimed-but-undelivered reminder to 'scheduled' for the next poll."""
    reminders.reschedule(reminder_id)
    return ReminderActionResponse(ok=True)


@router.post("/{reminder_id}/cancel", response_model=ReminderActionResponse,
             dependencies=[Depends(require_internal_token)])
def cancel(reminder_id: int) -> ReminderActionResponse:
    reminders.cancel(reminder_id)
    return ReminderActionResponse(ok=True)


@router.post("/{reminder_id}/done", response_model=ReminderActionResponse,
             dependencies=[Depends(require_internal_token)])
def done(reminder_id: int) -> ReminderActionResponse:
    reminders.mark_done(reminder_id)
    return ReminderActionResponse(ok=True)
