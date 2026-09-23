"""One completed hop, as the next hop sees it."""

from dataclasses import dataclass

from agents.contracts.ref import Ref
from agents.contracts.status import Status


@dataclass(frozen=True)
class HistoryEntry:
    """One completed hop, as the next hop sees it.

    There is no free-text field. The broker derives this from an `AgentResult`,
    so an agent cannot describe itself badly — it does not describe itself.

    It also carries no `state`: the full working state lives in `agent_states`
    and is reachable only through the `read_state` tool, gated by `may_read`.
    `state_id` is the handle for that call — without it an agent could be told
    a hop happened but have no way to ask what it did.
    """

    agent: str
    status: Status
    produced: tuple[Ref, ...] = ()
    error: str | None = None
    state_id: str | None = None
