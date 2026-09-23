"""Every shape the agents and the broker exchange, one type per module.

Nothing here does I/O, holds module state, or imports an agent, a tool, or the
broker. That is what makes it the bottom of the dependency graph: the loop, the
router, the store and four agents can agree on shapes without importing each
other, which is what lets the broker route a turn with no agent naming another.

Three groups:

  - **what an agent implements and exchanges** — `AgentSpec`, `AgentRequest`,
    `AgentResult`;
  - **what a turn is made of** — `UserContext`, `Ref`, `HistoryEntry`, `Status`;
  - **what a turn hands back** — `TurnOutcome`.

Plus two that belong to an agent's own working, not to the broker's: `ToolResult`
(what every tool returns) and `PlanRequest` (what enrich and reminder plan from).

Import from this package rather than the leaf module — the split is an
implementation detail, so `from agents.contracts import AgentSpec` keeps working
if a type moves. See `devdoc/agent-broker.md`.
"""

from agents.contracts.agent_request import AgentRequest
from agents.contracts.agent_result import AgentResult
from agents.contracts.agent_spec import AgentSpec
from agents.contracts.history_entry import HistoryEntry
from agents.contracts.plan_request import PlanRequest
from agents.contracts.ref import Ref
from agents.contracts.status import Status
from agents.contracts.tool_result import ToolResult
from agents.contracts.turn_outcome import TurnOutcome
from agents.contracts.user_context import UserContext

__all__ = [
    "AgentRequest",
    "AgentResult",
    "AgentSpec",
    "HistoryEntry",
    "PlanRequest",
    "Ref",
    "Status",
    "ToolResult",
    "TurnOutcome",
    "UserContext",
]
