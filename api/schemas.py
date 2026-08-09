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
