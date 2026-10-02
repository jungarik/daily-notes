"""Addnote router — the Add note page's data.

One method for now: the note a tapped Edit opens. The page's writes (create,
update) have no endpoint yet, which is why its tick is disabled; when they
arrive they belong here, beside this read.
"""

from fastapi import APIRouter, Depends, HTTPException

from api.deps import current_user
from api.addnote import db, helper
from api.addnote.schemas import EditableNote

router = APIRouter(prefix="/api/addnote", tags=["addnote"])


@router.get("/{note_id}", response_model=EditableNote)
def get_note(note_id: int, user_id: int = Depends(current_user)) -> EditableNote:
    """The note being edited, owner-scoped.

    404 covers both "no such note" and "not yours": a caller who does not own
    it learns nothing about whether it exists. Same reasoning as the section's
    delete, and the same single query — the ownership predicate is in the SQL.
    """
    row = db.note_for_user(user_id, note_id)

    if row is None:
        raise HTTPException(status_code=404, detail="note not found")

    return EditableNote(**helper.editable_note(row))
