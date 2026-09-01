from typing import Literal, TypedDict


class ActionProposal(TypedDict):
    name: str
    args: dict
    summary: str


class RelatedNote(TypedDict):
    note_id: int
    title: str
    path: str | None
    distance: float


class CaptureProposal(TypedDict):
    """Editable preview returned by the standalone Enrich capture flow."""

    action_id: str
    status: Literal["proposed"]
    action: ActionProposal
    related_notes: list[RelatedNote]
