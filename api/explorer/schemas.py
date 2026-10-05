"""Response models for the explorer section."""

from pydantic import BaseModel


class ExplorerNote(BaseModel):
    """A row in the tree. `label` is the note's opening words (60 chars);
    `snippet` is the longer 160-char preview under it."""
    id: int
    label: str
    path: str | None = None
    snippet: str = ""
    created_at: str | None = None
    links: int = 0


class VaultRoot(BaseModel):
    """One top-level folder of the vault, in the order it should be shown.

    The client builds its tree from localised path strings and has no notion of
    a root key, so it cannot know that "Архів" belongs last. This roster is how
    that order reaches it.
    """

    key: str
    label: str


class ExplorerPayload(BaseModel):
    notes: list[ExplorerNote] = []
    roots: list[VaultRoot] = []
