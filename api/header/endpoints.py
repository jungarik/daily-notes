"""Header router — GET /api/header/stats. Notes / Links / Reminders counts."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import current_user
from api.header import helper

router = APIRouter(prefix="/api/header", tags=["header"])


class HeaderStats(BaseModel):
    notes: int = 0
    links: int = 0
    reminders: int = 0


@router.get("/stats", response_model=HeaderStats)
def stats(user_id: int = Depends(current_user)) -> HeaderStats:
    return HeaderStats(**helper.stats(user_id))
