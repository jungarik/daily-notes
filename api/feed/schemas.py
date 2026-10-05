"""Response models for the feed section."""

from pydantic import BaseModel


class FeedLink(BaseModel):
    """A linked note's chip. `label` rather than `title`: it carries the start
    of the note's own text, not the enriched `notes.title`."""
    id: int
    label: str


class FeedAttachment(BaseModel):
    id: int
    kind: str = "image"
    mime: str | None = None
    url: str


class FeedCard(BaseModel):
    """One note as the feed renders it.

    `label` is the first 60 characters of `text`, not the note's enriched
    `title` — the web app shows the user's own opening words everywhere rather
    than an LLM's summary of them. `notes.title` still exists; nothing here
    reads it.
    """
    id: int
    label: str
    path: str | None = None
    text: str = ""
    tags: list[str] = []
    type: str | None = None
    created_at: str | None = None
    links: list[FeedLink] = []
    backlinks: list[FeedLink] = []
    attachments: list[FeedAttachment] = []
