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
    delete, and the ownership predicate is in the SQL rather than a check after
    the fact.

    The endpoint is the impure boundary: it resolves the caller, performs the
    reads, and signs the attachment URLs (which reads the clock and a secret).
    The ownership check is the first read's `WHERE`, and the two follow-up
    reads happen only once it has passed — so an id that is not the caller's is
    never used to query links or attachments at all.

    The response is built here rather than through a mapper. Three of the
    row's columns are nullable where the client needs a value: `text` and
    `path` feed *controlled* React inputs, where `null` means uncontrolled —
    React warns and the field stops tracking its own state — and `tags` is a
    nullable jsonb the client renders with `.map`, which throws on `null`. So
    an absent value becomes the empty string or the empty list, which is what
    "not filed yet" and "no tags" actually are. That is three `or` expressions
    at the one place that already owns the reads; a mapper for it would be a
    name to read past. Pydantic ignores the row's other columns and copies the
    lists, so nothing is smuggled into the payload and nothing the caller still
    holds can change it afterwards.
    """
    row = db.note_for_user(user_id, note_id)

    if row is None:
        raise HTTPException(status_code=404, detail="note not found")

    return EditableNote(
        id=row["id"],
        text=row["text"] or "",
        path=row["path"] or "",
        tags=row["tags"] or [],
        attachments=helper.attachment_views(db.attachments(note_id)),
        linked_note_ids=db.linked_note_ids(user_id, note_id),
    )
