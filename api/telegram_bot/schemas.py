"""Request/response models for the telegram_bot section."""

from pydantic import BaseModel, Field


class ReminderInfo(BaseModel):
    id: int
    remind_at: str


class CaptureRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class CaptureResponse(BaseModel):
    note_id: int | None = None
    text: str | None = None
    reminder: ReminderInfo | None = None


class PathsResponse(BaseModel):
    paths: list[str]


class SetPathRequest(BaseModel):
    path: str = Field(min_length=1, max_length=200)


class NoteMeta(BaseModel):
    type: str | None = None
    title: str | None = None
    path: str | None = None
    tags: list[str] = []
    priority: str | None = None


class AtomizedNote(BaseModel):
    note_id: int
    text: str


class AtomizeResponse(BaseModel):
    atoms: list[AtomizedNote] = []


class DeleteResponse(BaseModel):
    deleted: bool


class PolishResponse(BaseModel):
    text: str | None = None


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


class ReminderItem(BaseModel):
    id: int
    remind_at: str
    text: str
    status: str


class RemindersResponse(BaseModel):
    reminders: list[ReminderItem]


class CountResponse(BaseModel):
    count: int


class SnoozeRequest(BaseModel):
    mode: str


class SnoozeResponse(BaseModel):
    remind_at: str


class ReminderActionResponse(BaseModel):
    ok: bool = True


class ClaimDueRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=500)


class ClaimedReminder(BaseModel):
    reminder_id: int
    user_id: int
    chat_id: int | None = None
    remind_at: str
    text: str
    locale: str


class ClaimDueResponse(BaseModel):
    reminders: list[ClaimedReminder]


class ResolveUserRequest(BaseModel):
    chat_id: int
    username: str | None = None


class ResolveUserResponse(BaseModel):
    user_id: int


class UserSettingsResponse(BaseModel):
    timezone: str | None = None
    language: str | None = None
    tz_name: str
    locale: str
    active_reminders: int = 0


class SetTimezoneRequest(BaseModel):
    timezone: str = Field(min_length=1, max_length=100)


class SetTimezoneResponse(BaseModel):
    timezone: str


class SetLanguageRequest(BaseModel):
    language: str = Field(min_length=1, max_length=20)


class SetLanguageResponse(BaseModel):
    language: str


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)


class SearchResponse(BaseModel):
    answer: str | None = None
