"""Composition root: the only module that wires concrete agents together.

One path, and one place an agent is named. Everything above this file — the
endpoint, the loop, the router — works in terms of the registry; everything
below it is an agent that knows nothing of its peers.
"""

import config
from agents.enricher import agent as enricher_agent
from agents.finder import agent as finder_agent
from agents.reminder import agent as reminder_agent
from agents.responder import agent as responder_agent
from agents.router import agent as router_agent
from agents.runtime import execution_ledger, state_store
from agents.runtime.loop import Loop
from agents.runtime.registry import AgentRegistry

# The farm. Agents register themselves as specs; the registry rejects a
# duplicate name or a tool name two agents both claim, here at import time.
# The router registers like any other — the loop reaches it by name.
agents = AgentRegistry()
agents.register(reminder_agent.SPEC)
agents.register(enricher_agent.SPEC)
agents.register(finder_agent.SPEC)
agents.register(responder_agent.SPEC)
agents.register(router_agent.SPEC)

# `always_route` forces the model router for every hop by skipping the
# entry-tool shortcut. On in dev and in the eval harness, so the path
# production almost never takes is the path a local turn always takes.
loop = Loop(
    state_store,
    execution_ledger,
    agents,
    max_hops=config.AGENT_MAX_HOPS,
    always_route=config.AGENT_ROUTER_ALWAYS,
)
