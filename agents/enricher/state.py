"""State and context helpers for enrichment graphs."""

from typing import Literal, TypedDict

from agents.contracts import UserContext


class EnrichState(TypedDict, total=False):
    messages: list[dict]
    user_context: dict
    steps: int
    tool_call: dict | None
    model_error: str | None
    status: Literal["answer", "confirm"]
    reply: str
    action: dict | None
    pending: dict | None
    completed_action_id: str | None
    link_proposal: dict
    metadata_text: str
    metadata_note_id: int | None
    metadata_context: dict
    raw_metadata: dict
    metadata: dict
    metadata_error: str | None
    metadata_trace: list[dict]


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


def context_from_state(state: EnrichState | ActionPlanState) -> UserContext:
    """The context this graph's state carries, under this graph's key.

    It comes back as it went in — the plain contract. Anything that needs a
    live clock calls `restore_clock` on it, which is the one place in the farm
    that conversion happens.
    """
    return state.get("user_context") or {}


def initial_state(ctx: UserContext, messages: list, pending: dict | None = None) -> EnrichState:
    action = None

    if pending:
        action = {
            "name": pending["name"],
            "args": pending["args"],
            "summary": pending["summary"],
        }

    return {
        "user_context": ctx,
        "messages": list(messages),
        "steps": 0,
        "tool_call": None,
        "pending": pending,
        "action": action,
        "completed_action_id": None,
    }
