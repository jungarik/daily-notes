"""Request/response models for the chat section.

The chat agent answers questions and hands off write requests to the enrich
agent, which pauses for confirmation — so a response is either an answer or a
`confirm` carrying the proposed action.
"""

from pydantic import BaseModel, Field


class ChatCitation(BaseModel):
    note_id: int
    title: str


class ChatAction(BaseModel):
    # The write the enrich agent proposes, awaiting the user's confirmation.
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
    status: str = "answer"             # "answer" | "confirm"
    reply: str | None = None          # set when status == "answer"
    action: ChatAction | None = None  # set when status == "confirm"
    citations: list[ChatCitation] = []
