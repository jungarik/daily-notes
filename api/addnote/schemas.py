"""Request/response models for the addnote section."""

from pydantic import BaseModel


class EditableAttachment(BaseModel):
    """One image on the note, as the editor can load it. `url` is the signed
    notecard proxy path, not a bucket URL — the bucket is private and the
    storage key never leaves the API."""
    id: int
    kind: str | None = None
    mime: str | None = None
    url: str


class EditableNote(BaseModel):
    """What the Add note page opens with.

    `linked_note_ids` is ids rather than chips: links are symmetric here (the
    note's own links plus its backlinks, de-duplicated — the set the card's
    chips show), and an id is also what a save would send back. Titles would be
    a second read for something the page has no control to render yet.
    """
    id: int
    text: str = ""
    path: str = ""
    tags: list[str] = []
    attachments: list[EditableAttachment] = []
    linked_note_ids: list[int] = []
