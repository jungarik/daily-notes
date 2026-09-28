"""Request/response models for the v2 chat section.

The wire shape is deliberately v1's, so the Mini App switches by changing a URL
and nothing else. What differs is who fills it in: the loop's `TurnOutcome`
rather than a single agent's graph result.

`citations` is absent on purpose. `TurnOutcome` carries no agent state, so the
answer's cited notes are not reachable here yet; v1 still serves chips while
both versions are live. See `devdoc/agent-loop.md`.
"""

from pydantic import BaseModel, Field


class ChatAction(BaseModel):
    # The write an agent proposes, awaiting the user's confirmation.
    name: str
    args: dict = {}
    summary: str
    # "confirm" = plain yes/no; "select" = the user picks ids (args.candidates).
    kind: str = "confirm"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: int | None = None


class ChatConfirmRequest(BaseModel):
    thread_id: int
    approve: bool
    # For a select action: the note ids the user chose to link.
    selection: list[int] | None = None


class ChatResponse(BaseModel):
    thread_id: int
    status: str = "answer"             # "answer" | "confirm"
    reply: str | None = None          # set when status == "answer"
    action: ChatAction | None = None  # set when status == "confirm"
