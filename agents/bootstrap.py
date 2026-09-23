"""Composition root: the only module that wires concrete agents together.

Two paths live here during the broker migration (`devdoc/agent-broker.md`). The
handoff dispatch below is what serves chat today. The `farm` broker beneath it is
the replacement, wired agent by agent; nothing calls it until an endpoint does.
"""

import config
from agents.broker import AgentRegistry, Broker, Router
from agents.broker import state_store
from agents.enrich import handoff_api as enrich_handoff
from agents.reminder import agent as reminder_agent
from agents.reminder import handoff_api as reminder_handoff
from agents.runtime import execution_ledger
from agents.runtime.handoff_dispatch import HandoffDispatch
from agents.runtime.specialist_registry import SpecialistRegistry
from tools.conversation import HANDOFF_SPECIALISTS

# Which agent serves each handoff mode. This is the only place an agent is
# named for routing; the graph nodes resolve a route and never name one.
MODE_AGENTS = {
    "enrich": "enrich",
    "reminder": "reminder",
}

registry = SpecialistRegistry()
registry.register("enrich", enrich_handoff)
registry.register("reminder", reminder_handoff)

broker = HandoffDispatch(registry)

for _tool_name, _mode in HANDOFF_SPECIALISTS.items():
    broker.register(_tool_name, MODE_AGENTS[_mode], _mode)


# The broker farm. Agents register themselves as specs; the registry rejects a
# duplicate name or a tool name two agents both claim, here at import time.
agents = AgentRegistry()
agents.register(reminder_agent.SPEC)

# `select_model` is the case-3 seam and is still empty: until the responder
# lands (Phase 4) a turn routes by entry tool or ends.
router = Router(agents, always_ask_model=config.AGENT_ROUTER_ALWAYS)

farm = Broker(
    state_store,
    execution_ledger,
    router,
    max_hops=config.AGENT_MAX_HOPS,
)
