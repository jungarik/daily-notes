"""The state the classifier's graph threads from gather to normalize.

Every key here lost a `metadata_` prefix on the way out of the enricher. It was
never describing the value — it was disambiguating it from the planning keys it
shared `ActionPlanState` with. In a state whose only subject is a note's
metadata, `metadata_text` is just `text`, and the prefix is noise a reader has
to strip on every line.

`trace` records which nodes and tools ran. It is for reading a turn back, and
the agent deliberately keeps it out of what it hands the next hop.
"""

from typing import TypedDict

from agents.contracts import UserContext


class ClassifyState(TypedDict, total=False):
    user_context: dict
    note_id: int | None
    text: str
    context: dict
    raw_metadata: dict
    metadata: dict
    error: str | None
    trace: list[dict]


def context_from_state(state: ClassifyState) -> UserContext:
    """The turn context this graph's state carries.

    It comes back as it went in — the plain contract. Anything that needs a
    live clock calls `restore_clock` on it, which is the one place in the farm
    that conversion happens.
    """
    return state.get("user_context") or {}
