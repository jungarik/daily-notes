"""Feed router — GET /api/feed. Full note cards, newest first."""

from fastapi import APIRouter, Depends

from api.deps import current_user
from api.feed import helper
from api.feed.schemas import FeedCard

router = APIRouter(prefix="/api/feed", tags=["feed"])


@router.get("", response_model=list[FeedCard])
def feed(user_id: int = Depends(current_user)) -> list[FeedCard]:
    return [FeedCard(**it) for it in helper.feed_for_user(user_id)]
