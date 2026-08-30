"""Notesheet router — GET /api/notesheet/{note_id}. One note's full detail."""

from fastapi import APIRouter, Depends, HTTPException

from api.deps import current_user
from api.notesheet import helper
from api.notesheet.schemas import NoteDetail

router = APIRouter(prefix="/api/notesheet", tags=["notesheet"])


@router.get("/{note_id}", response_model=NoteDetail)
def note_detail(note_id: int, user_id: int = Depends(current_user)) -> NoteDetail:
    detail = helper.note_detail(user_id, note_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="note not found")
    return NoteDetail(**detail)
