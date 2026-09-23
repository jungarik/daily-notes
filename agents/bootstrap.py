"""Composition root: the only module that wires concrete agents together.

One path, and one place an agent is named. Everything above this file — the
endpoint, the broker, the router — works in terms of the registry; everything
below it is an agent that knows nothing of its peers.
"""

import config
from agents.broker import AgentRegistry, Broker, Router
from agents.broker import state_store
from agents.broker.model_selector import select_agent_name
from agents.enrich import agent as enrich_agent
from agents.finder import agent as finder_agent
from agents.reminder import agent as reminder_agent
from agents.responder import agent as responder_agent
from agents.runtime import execution_ledger

# The farm. Agents register themselves as specs; the registry rejects a
# duplicate name or a tool name two agents both claim, here at import time.
agents = AgentRegistry()
agents.register(reminder_agent.SPEC)
agents.register(enrich_agent.SPEC)
agents.register(finder_agent.SPEC)
agents.register(responder_agent.SPEC)

# Case 3: when no entry tool resolves a hop, a model picks from the roster. It
# declines rather than guessing, and the router then falls through to the
# responder, which takes the last hop.
router = Router(
    agents,
    select_model=select_agent_name,
    always_ask_model=config.AGENT_ROUTER_ALWAYS)

farm = Broker(
    state_store,
    execution_ledger,
    router,
    max_hops=config.AGENT_MAX_HOPS,
)
