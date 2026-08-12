"""Pydantic request/response models for the API.

Validation/guardrails live here (the edge): bounded query length, etc. — so
handlers receive already-clean input. Clients pass only identifiers (user_id);
per-user attributes (timezone, language) are resolved server-side from user_id.
"""

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    user_id: int
    query: str = Field(min_length=1, max_length=1000)


class SearchResponse(BaseModel):
    answer: str | None = None


class ResolveUserRequest(BaseModel):
    # External client identity. Today the only client is Telegram, whose chat_id
    # is stored on the users row; other clients will add their own identity later.
    chat_id: int


class ResolveUserResponse(BaseModel):
    user_id: int


class PathsResponse(BaseModel):
    paths: list[str]


class SetPathRequest(BaseModel):
    path: str = Field(min_length=1, max_length=200)


class EnrichRequest(BaseModel):
    user_id: int


class NoteMeta(BaseModel):
    type: str | None = None
    title: str | None = None
    path: str | None = None
    tags: list[str] = []
    priority: str | None = None


class ReminderActionResponse(BaseModel):
    ok: bool = True


class SnoozeRequest(BaseModel):
    user_id: int
    mode: str  # "tomorrow" or a whole number of minutes, e.g. "10"


class SnoozeResponse(BaseModel):
    remind_at: str  # ISO-8601, in the user's timezone
