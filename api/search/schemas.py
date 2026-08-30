"""Response models for the search section."""

from pydantic import BaseModel


class SearchHit(BaseModel):
    id: int
    title: str
    path: str | None = None
    snippet: str = ""
