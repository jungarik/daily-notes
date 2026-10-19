"""Response models for the viewnote section."""

from datetime import datetime

from pydantic import BaseModel


class ViewableAttachment(BaseModel):
    """One image on the note, as the viewer can load it. `url` is the signed
    notecard proxy path, not a bucket URL — the bucket is private and the
    storage key never leaves the API."""
    id: int
    kind: str | None = None
    mime: str | None = None
    url: str


class ViewableNote(BaseModel):
    """What the View note page opens with.

    `linked_note_ids` is ids rather than chips: links are symmetric here (the
    note's own links plus its backlinks, de-duplicated — the set the card's
    chips show), and titles would be a second read for something the page has no
    control to render yet.

    Timestamps are UTC instants; the user's own zone rides along so the client
    formats them on their clock rather than the server's, and is None for a
    Mini-App-only user who never set one (the client then uses the device's).
    """
    id: int
    text: str = ""
    path: str = ""
    tags: list[str] = []
    attachments: list[ViewableAttachment] = []
    linked_note_ids: list[int] = []
    created_at: datetime | None = None
    updated_at: datetime | None = None
    timezone: str | None = None
    is_favorite: bool = False


class RootsPayload(BaseModel):
    """The root wheel's roster: the vault's root folders in canonical order, in
    the user's language — the client renders it as given rather than re-deriving
    an order it would need `config.ROOT_FOLDERS` to know.

    `default_root` is where a note goes when nothing is chosen, so the page can
    show that destination instead of an empty control.
    """
    roots: list[str] = []
    default_root: str = ""


class ChildrenPayload(BaseModel):
    """The sub-folder wheel's roster: the distinct second-level folder names the
    user already files notes under inside one root. Names, not paths — the client
    joins them onto the root it asked about."""
    children: list[str] = []


class FavoriteRequest(BaseModel):
    """Set, not toggle: sending the state you want makes a retried request
    harmless, where a toggle would undo itself."""
    is_favorite: bool


class FavoritePayload(BaseModel):
    """The flag as stored, so the client shows what the server holds."""
    is_favorite: bool
