"""Response models for the feed section."""

from pydantic import BaseModel


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
