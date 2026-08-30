"""Notesheet router — GET /api/notesheet/{note_id}. One note's full detail."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import current_user
from api.notesheet import helper

router = APIRouter(prefix="/api/notesheet", tags=["notesheet"])


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


@router.get("/{note_id}", response_model=NoteDetail)
def note_detail(note_id: int, user_id: int = Depends(current_user)) -> NoteDetail:
    detail = helper.note_detail(user_id, note_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="note not found")
    return NoteDetail(**detail)
