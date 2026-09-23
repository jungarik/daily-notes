"""One hop's output."""

from dataclasses import dataclass, field

from agents.contracts.ref import Ref
from agents.contracts.status import Status


@dataclass(frozen=True)
class AgentResult:
    """One hop's output.

    `state` is everything the run produced and is saved whole. `produced` is the
    subset the next hop is allowed to see without a `read_state` call — keep it
    to refs, never prose. An agent that never pauses simply never returns
    `needs_input`.

    `reply` is the turn's user-facing text. In practice only the responder sets
    it, but it is a declared field rather than a `state` key so the broker can
    carry it out without looking inside an agent's state or knowing which agent
    the responder is.
    """

    status: Status
    state: dict = field(default_factory=dict)
    produced: tuple[Ref, ...] = ()
    ask: dict | None = None
    token: str | None = None
    error: str | None = None
    reply: str | None = None
