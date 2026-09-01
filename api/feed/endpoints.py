"""Feed router — GET /api/feed. Full note cards, newest first."""

from fastapi import APIRouter, Depends

from api.deps import current_user
from api.feed import db, helper
from api.feed.schemas import FeedCard

router = APIRouter(prefix="/api/feed", tags=["feed"])


@router.get("", response_model=list[FeedCard])
def feed(user_id: int = Depends(current_user)) -> list[FeedCard]:
    notes = db.list_notes(user_id)
    edges = db.all_links(user_id)
    linked_note_ids = {note_id for edge in edges for note_id in edge}
    briefs = db.notes_brief(user_id, linked_note_ids)
    attachment_rows = db.attachments_for_notes([note["id"] for note in notes])
    attachments = {
        note_id: helper.attachment_views(rows)
        for note_id, rows in attachment_rows.items()
    }
    return [
        FeedCard(**item)
        for item in helper.feed_for_user(notes, edges, briefs, attachments)
    ]
