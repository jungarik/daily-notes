"""Composition root: the only module that wires concrete specialists together."""

from agents.enrich import api as enrich_api
from agents.runtime.specialist_registry import SpecialistRegistry


registry = SpecialistRegistry()
registry.register("enrich", enrich_api)
