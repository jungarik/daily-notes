"""Feed router — GET /api/feed. Full note cards, newest first.

Response models are defined here (section-local) so the folder is decoupled from
the shared api/schemas.py.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import current_user
from api.feed import helper

router = APIRouter(prefix="/api/feed", tags=["feed"])


class FeedLink(BaseModel):
    id: int
    title: str


class FeedAttachment(BaseModel):
    id: int
    kind: str = "image"
    mime: str | None = None
    url: str


class FeedCard(BaseModel):
    id: int
    title: str
    path: str | None = None
    text: str = ""
    tags: list[str] = []
    type: str | None = None
    created_at: str | None = None
    links: list[FeedLink] = []
    backlinks: list[FeedLink] = []
    attachments: list[FeedAttachment] = []


@router.get("", response_model=list[FeedCard])
def feed(user_id: int = Depends(current_user)) -> list[FeedCard]:
    return [FeedCard(**it) for it in helper.feed_for_user(user_id)]
