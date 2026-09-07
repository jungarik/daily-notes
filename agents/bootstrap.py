"""Composition root: the only module that wires concrete specialists together."""

from agents.enrich import api as enrich_api
from agents.runtime.handoff_broker import HandoffBroker
from agents.runtime.specialist_registry import SpecialistRegistry
from tools.conversation import HANDOFF_SPECIALISTS

# Every handoff mode is served by the enrich specialist today. When a second
# specialist appears, map its modes to that agent here — the graph nodes never
# name an agent themselves.
MODE_AGENTS = {
    "enrich": "enrich",
    "reminder": "enrich",
}

registry = SpecialistRegistry()
registry.register("enrich", enrich_api)

broker = HandoffBroker(registry)

for _tool_name, _mode in HANDOFF_SPECIALISTS.items():
    broker.register(_tool_name, MODE_AGENTS[_mode], _mode)
