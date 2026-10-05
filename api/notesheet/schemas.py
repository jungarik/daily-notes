"""Response models for the notesheet section."""

from pydantic import BaseModel


class SheetLink(BaseModel):
    """A neighbour's chip. `label` is the start of that note's own text."""
    id: int
    label: str


class SheetAttachment(BaseModel):
    id: int
    kind: str = "image"
    mime: str | None = None
    url: str


class NoteDetail(BaseModel):
    """The preview sheet's note. `label` is its opening words, not its
    enriched `title`."""
    id: int
    label: str
    path: str | None = None
    text: str = ""
    tags: list[str] = []
    type: str | None = None
    created_at: str | None = None
    links: list[SheetLink] = []
    backlinks: list[SheetLink] = []
    attachments: list[SheetAttachment] = []
