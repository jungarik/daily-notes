"""Response models for the notesheet section."""

from pydantic import BaseModel


class SheetLink(BaseModel):
    id: int
    title: str


class SheetAttachment(BaseModel):
    id: int
    kind: str = "image"
    mime: str | None = None
    url: str


class NoteDetail(BaseModel):
    id: int
    title: str
    path: str | None = None
    text: str = ""
    tags: list[str] = []
    type: str | None = None
    created_at: str | None = None
    links: list[SheetLink] = []
    backlinks: list[SheetLink] = []
    attachments: list[SheetAttachment] = []
