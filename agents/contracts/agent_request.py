"""One hop's input."""

from dataclasses import dataclass, field

from agents.contracts.history_entry import HistoryEntry
from agents.contracts.user_context import UserContext


@dataclass(frozen=True)
class AgentRequest:
    """One hop's input.

    `correlation_id` names the turn and `causation_id` names the state that
    produced this hop, so a whole turn reconstructs as a tree from the saved
    states alone.

    `context` is what every turn carries; `references` is material the caller had
    already resolved and thought worth passing on (note ids, citations, a
    conversation summary). They are separate so the shared contract does not grow
    a field per agent — an agent that wants more calls its `read_state` tool.
    """

    request_id: str
    correlation_id: str
    causation_id: str | None
    agent: str
    message: str
    context: UserContext
    references: dict = field(default_factory=dict)
    history: tuple[HistoryEntry, ...] = ()
    hops_left: int = 0
