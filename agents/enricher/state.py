"""State and context helpers for enrichment graphs."""

from typing import TypedDict

from agents.contracts import UserContext


class ActionPlanState(TypedDict, total=False):
    messages: list[dict]
    user_context: dict
    tool_specs: list[dict]
    steps: int
    tool_call: dict | None
    model_error: str | None
    action: dict | None
    link_proposal: dict
    metadata_text: str
    metadata_note_id: int | None
    metadata_context: dict
    raw_metadata: dict
    metadata: dict
    metadata_error: str | None
    metadata_trace: list[dict]


class MetadataState(TypedDict, total=False):
    user_id: int
    metadata_text: str
    metadata_note_id: int | None
    metadata_context: dict
    raw_metadata: dict
    metadata: dict
    metadata_error: str | None
    metadata_trace: list[dict]
    tool_call: dict | None
    context: dict


def context_from_state(state: ActionPlanState) -> UserContext:
    """The context this graph's state carries, under this graph's key.

    It comes back as it went in — the plain contract. Anything that needs a
    live clock calls `restore_clock` on it, which is the one place in the farm
    that conversion happens.
    """
    return state.get("user_context") or {}


