"""
Reminder action endpoints.

The inline reminder buttons (Cancel / Done / Snooze) go through here. Snooze
resolves the new time from the user's timezone server-side, so the client only
passes a mode. All logic lives in the `reminders` service.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from services import reminders
from api.deps import require_internal_token
from api.schemas import ReminderActionResponse, SnoozeRequest, SnoozeResponse

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal/reminders",
    tags=["reminders"],
    dependencies=[Depends(require_internal_token)],
)


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
