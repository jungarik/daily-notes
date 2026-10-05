"""Response models for the search section."""

from pydantic import BaseModel


class SearchHit(BaseModel):
    """A result row. `label` is the note's opening words (60 chars); `snippet`
    is the longer preview."""
    id: int
    label: str
    path: str | None = None
    snippet: str = ""
