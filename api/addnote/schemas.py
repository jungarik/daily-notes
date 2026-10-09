"""Request/response models for the addnote section."""

from pydantic import BaseModel, Field


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


class RootsPayload(BaseModel):
    """The root wheel's roster: the vault's root folders in canonical order,
    in the user's language — the client renders it as given rather than
    re-deriving an order it would need `config.ROOT_FOLDERS` to know.

    `default_root` is where a note goes when the user picks nothing, so the
    page can show that destination instead of an empty control that saves
    somewhere anyway.
    """
    roots: list[str] = []
    default_root: str = ""


class ChildrenPayload(BaseModel):
    """The sub-folder wheel's roster: the distinct second-level folder names
    the user already files notes under inside one root. Names, not paths — the
    client joins them onto the root it asked about."""
    children: list[str] = []


class SaveNoteRequest(BaseModel):
    """What the editor sends on save.

    `linked_note_ids` is deliberately absent: the editor shows a note's
    neighbours but has no control for changing them, and a save that silently
    rewrote the link graph from a read-only display would be the worst kind of
    surprise. Links stay the ⋮ menu's and the bot's business.

    Attachments are absent for the same reason — the page has no way to add or
    remove one yet.
    """
    text: str = Field(min_length=1, max_length=20000)
    # Empty is not missing: it means "wherever notes go by default", which the
    # endpoint resolves to the configured root.
    path: str = Field(default="", max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=50)
