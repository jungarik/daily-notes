"""Request/response models for the addnote section."""

from pydantic import BaseModel


class EditableNote(BaseModel):
    """What the Add note page opens with. One field beyond the id, matching
    the one control the page has wired — it grows when the page does."""
    id: int
    text: str = ""
