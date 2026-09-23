"""Every type the broker passes around, in one place.

Three groups, all frozen dataclasses or a TypedDict — no I/O, no module state,
and no import of any agent, tool, or other broker module:

  - what an agent implements and exchanges: `AgentSpec`, `AgentRequest`,
    `AgentResult`;
  - what the turn is made of: `UserContext`, `Ref`, `HistoryEntry`;
  - what a turn hands back to the caller: `TurnOutcome`.

This module depends on nothing and everything else depends on it, which is the
edge that lets the broker route a turn without any agent naming another — and
lets the loop, the router and the store agree on shapes without importing each
other.

See `devdoc/agent-broker.md`.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, TypedDict

Status = Literal["done", "needs_input", "failed"]


class UserContext(TypedDict, total=False):
    """Who the turn belongs to, and the clock to resolve it against.

    Plain JSON by design: `now` and `tz` travel as strings so the envelope stays
    serialisable, and each agent restores them against its own clock. A confirm
    arriving ten minutes later carries a *different* context, which is the point.

    `user_id` is the one key an agent can count on — it is the turn's owner, and
    the only place that owner is written down. Everything else is optional, so an
    agent reading a key it was not given falls back rather than failing.

    Every key is optional to the type checker (`total=False`), so `user_id` is
    enforced at runtime instead: the broker subscripts it, and a context without
    one raises rather than writing a row for nobody.
    """

    user_id: int
    now: str
    tz: str | None
    locale: str


@dataclass(frozen=True)
class Ref:
    """A typed pointer to something an agent made.

    `kind` is the agent's own word for it ("note", "reminder", "link"). The
    broker checks that it is a non-empty string sitting next to an id and never
    reads the value, so the farm needs no shared domain vocabulary.
    """

    kind: str
    id: str


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


@dataclass(frozen=True)
class AgentSpec:
    """How one agent joins the farm.

    `entry_tools` are the tool names that route here with no model call — the
    agent declares what addresses it, and the broker owns the lookup. `may_read`
    is the allowlist for this agent's `read_state` tool; `("*",)` means every
    agent in the turn.

    `resume(token, decision, context)` takes a fresh context because a
    confirmation arrives in a later request: the clock has moved on since the
    ask, and the agent must resolve against now, not against then.
    """

    name: str
    description: str
    start: Callable[[AgentRequest], AgentResult]
    resume: Callable[[str, dict, UserContext], AgentResult] | None = None
    entry_tools: tuple[str, ...] = ()
    may_read: tuple[str, ...] = ()


@dataclass(frozen=True)
class TurnOutcome:
    """What one call into the broker gives back to the endpoint.

    `pending` is set only on `needs_input`: it is what the calling section stores
    so a later confirm can find this turn again.
    """

    status: str
    correlation_id: str
    history: tuple[HistoryEntry, ...]
    pending: dict | None = None
    reply: str | None = None
