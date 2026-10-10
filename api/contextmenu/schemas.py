"""Request/response models for the contextmenu section."""

from pydantic import BaseModel, Field


class SetPathRequest(BaseModel):
    path: str = Field(min_length=1, max_length=200)


class NoteMeta(BaseModel):
    type: str | None = None
    title: str | None = None
    path: str | None = None
    tags: list[str] = []
    priority: str | None = None


class MoveFolderRequest(BaseModel):
    old_path: str = Field(min_length=1, max_length=200)
    new_path: str = Field(min_length=1, max_length=200)


class MoveFolderResponse(BaseModel):
    count: int
    new_path: str


class RootsPayload(BaseModel):
    """The root selector's roster: the vault's root folders in canonical order,
    in the user's language — the client renders it as given rather than
    re-deriving an order it would need `config.ROOT_FOLDERS` to know."""
    roots: list[str] = []


class ChildrenPayload(BaseModel):
    """The sub-folder selector's roster: the distinct second-level folder names
    the user already files notes under inside one root. Names, not paths — the
    client joins them onto the root it asked about."""
    children: list[str] = []
