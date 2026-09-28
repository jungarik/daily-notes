"""State and context helpers for the enrichment graph.

The metadata channels are gone with the nodes that filled them. They lived here
because the classify pipeline ran mid-plan and had to thread its working values
through the planner's own state; that pipeline is the classifier agent now, and
it carries them in a state of its own (`agents/classifier/state.py`).
"""

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


def context_from_state(state: ActionPlanState) -> UserContext:
    """The context this graph's state carries, under this graph's key.

    It comes back as it went in — the plain contract. Anything that needs a
    live clock calls `restore_clock` on it, which is the one place in the farm
    that conversion happens.
    """
    return state.get("user_context") or {}
