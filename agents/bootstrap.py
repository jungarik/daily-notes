"""Composition root: the only module that wires concrete specialists together."""

from agents.enrich import handoff_api as enrich_handoff
from agents.reminder import handoff_api as reminder_handoff
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
