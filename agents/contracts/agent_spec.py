"""How one agent joins the farm."""

from collections.abc import Callable
from dataclasses import dataclass

from agents.contracts.agent_request import AgentRequest
from agents.contracts.agent_result import AgentResult
from agents.contracts.user_context import UserContext


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
