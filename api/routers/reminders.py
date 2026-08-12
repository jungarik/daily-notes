"""
Reminder action endpoints.

The inline reminder buttons (Cancel / Done / Snooze) go through here. Snooze
resolves the new time from the user's timezone server-side, so the client only
passes a mode. All logic lives in the `reminders` service.
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

import config
from services import reminders
from services import user_service
from api.deps import require_internal_token
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

router = APIRouter(
    prefix="/internal/reminders",
    tags=["reminders"],
    dependencies=[Depends(require_internal_token)],
)


@router.get("", response_model=RemindersResponse)
def list_reminders(user_id: int) -> RemindersResponse:
    """A user's upcoming (scheduled/postponed) reminders, soonest first."""
    rows = reminders.upcoming(user_id)
    return RemindersResponse(reminders=[
        ReminderItem(
            id=_id, remind_at=remind_at.isoformat(), text=text, status=status,
        )
        for (_id, remind_at, text, status) in rows
    ])


@router.get("/count", response_model=CountResponse)
def count(user_id: int) -> CountResponse:
    """How many active reminders a user has."""
    return CountResponse(count=reminders.active_count(user_id))


@router.post("/claim-due", response_model=ClaimDueResponse)
def claim_due(req: ClaimDueRequest) -> ClaimDueResponse:
    """Atomically claim due reminders for delivery. The client (which owns the
    transport) sends each and then calls /done or /retry. 'now' and the stale
    threshold are resolved server-side; the resolved locale rides along so the
    client doesn't need a settings round trip per reminder."""
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=config.SENDING_STALE_SECONDS)
    rows = reminders.claim_due(now, stale_before, req.limit)
    return ClaimDueResponse(reminders=[
        ClaimedReminder(
            reminder_id=_id, user_id=user_id, chat_id=chat_id,
            remind_at=remind_at.isoformat(), text=text,
            locale=user_service.language(user_id),
        )
        for (_id, user_id, chat_id, text, remind_at) in rows
    ])


@router.post("/{reminder_id}/retry", response_model=ReminderActionResponse)
def retry(reminder_id: int) -> ReminderActionResponse:
    """Return a claimed-but-undelivered reminder to 'scheduled' for the next poll."""
    reminders.reschedule(reminder_id)
    return ReminderActionResponse(ok=True)


@router.post("/{reminder_id}/cancel", response_model=ReminderActionResponse)
def cancel(reminder_id: int) -> ReminderActionResponse:
    reminders.cancel(reminder_id)
    return ReminderActionResponse(ok=True)


@router.post("/{reminder_id}/done", response_model=ReminderActionResponse)
def done(reminder_id: int) -> ReminderActionResponse:
    reminders.mark_done(reminder_id)
    return ReminderActionResponse(ok=True)


@router.post("/{reminder_id}/snooze", response_model=SnoozeResponse)
def snooze(reminder_id: int, req: SnoozeRequest) -> SnoozeResponse:
    if req.mode != "tomorrow" and not req.mode.isdigit():
        raise HTTPException(status_code=422, detail="mode must be 'tomorrow' or minutes")
    new_time = reminders.snooze(reminder_id, req.user_id, req.mode)
    return SnoozeResponse(remind_at=new_time.isoformat())
