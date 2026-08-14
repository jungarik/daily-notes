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
    # Optional display identity recorded on the user at create/resolve time.
    username: str | None = None


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


# --- User settings ---

class UserSettingsResponse(BaseModel):
    # Raw stored values (None when the user hasn't set them) plus the effective
    # values with defaults applied server-side, so the client formats without
    # knowing the defaults.
    timezone: str | None = None       # raw stored IANA name, or None
    language: str | None = None       # raw stored code, or None
    tz_name: str                      # effective IANA name (default applied)
    locale: str                       # effective 'en'/'uk' (default applied)
    active_reminders: int = 0         # count of scheduled/postponed reminders


class SetTimezoneRequest(BaseModel):
    user_id: int
    timezone: str = Field(min_length=1, max_length=100)


class SetTimezoneResponse(BaseModel):
    timezone: str


class SetLanguageRequest(BaseModel):
    user_id: int
    language: str = Field(min_length=1, max_length=20)


class SetLanguageResponse(BaseModel):
    language: str


# --- Capture ---

class ReminderInfo(BaseModel):
    id: int
    remind_at: str  # ISO-8601, tz-aware (user's timezone)


class CaptureRequest(BaseModel):
    user_id: int
    text: str = Field(min_length=1, max_length=20000)


class CaptureResponse(BaseModel):
    # For voice, note_id is None and text is "" when nothing usable was heard.
    note_id: int | None = None
    text: str | None = None
    reminder: ReminderInfo | None = None


class AtomizedNote(BaseModel):
    note_id: int
    text: str


class AtomizeResponse(BaseModel):
    # Empty when the note was already a single idea (nothing was created).
    atoms: list[AtomizedNote] = []


class DeleteResponse(BaseModel):
    # False when the guard blocked deletion (the note has metadata or links).
    deleted: bool


# --- Links ---

class LinkCandidate(BaseModel):
    note_id: int
    title: str | None = None
    path: str | None = None
    tags: list[str] = []
    score: float | None = None
    linked: bool = False


class LinkCandidatesResponse(BaseModel):
    candidates: list[LinkCandidate]


class ToggleLinkResponse(BaseModel):
    linked: bool


# --- Reminder listing / dispatch ---

class ReminderItem(BaseModel):
    id: int
    remind_at: str  # ISO-8601, tz-aware (UTC as stored)
    text: str
    status: str


class RemindersResponse(BaseModel):
    reminders: list[ReminderItem]


class CountResponse(BaseModel):
    count: int


class ClaimDueRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=500)


class ClaimedReminder(BaseModel):
    reminder_id: int
    user_id: int
    chat_id: int | None = None
    remind_at: str  # ISO-8601, tz-aware (UTC)
    text: str
    locale: str


class ClaimDueResponse(BaseModel):
    reminders: list[ClaimedReminder]
