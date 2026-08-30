"""Header router — GET /api/header/stats. Notes / Links / Reminders counts."""

from fastapi import APIRouter, Depends

from api.deps import current_user
from api.header import helper
from api.header.schemas import HeaderStats

router = APIRouter(prefix="/api/header", tags=["header"])


@router.get("/stats", response_model=HeaderStats)
def stats(user_id: int = Depends(current_user)) -> HeaderStats:
    return HeaderStats(**helper.stats(user_id))
