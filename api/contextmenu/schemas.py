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
