"""Request/response models for the chat section."""

from pydantic import BaseModel, Field


class ChatCitation(BaseModel):
    note_id: int
    title: str


class ChatAction(BaseModel):
    name: str
    args: dict = {}
    summary: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: int | None = None


class ChatConfirmRequest(BaseModel):
    thread_id: int
    approve: bool


class ChatResponse(BaseModel):
    thread_id: int
    status: str                       # "answer" | "confirm"
    reply: str | None = None
    action: ChatAction | None = None
    citations: list[ChatCitation] = []
