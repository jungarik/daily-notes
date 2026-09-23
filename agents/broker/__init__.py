"""The agents broker: routing, the turn tree, and the contracts agents implement.

See `devdoc/agent-broker.md`. The composition root (`agents/bootstrap.py`) is the
only place that builds a `Broker` — everything here takes its collaborators as
parameters.
"""

from agents.broker.broker import Broker, generate_action_id
from agents.broker.contracts import (
    AgentRequest,
    AgentResult,
    AgentSpec,
    HistoryEntry,
    Ref,
    TurnOutcome,
    UserContext,
)
from agents.broker.registry import AgentRegistry
from agents.broker.router import Router

__all__ = [
    "AgentRegistry",
    "AgentRequest",
    "AgentResult",
    "AgentSpec",
    "Broker",
    "HistoryEntry",
    "Ref",
    "Router",
    "UserContext",
    "TurnOutcome",
    "generate_action_id",
]
