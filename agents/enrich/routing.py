"""Conditional routing decisions for both Enrich workflows."""

from langgraph.graph import END

import config
from agents.enrich.state import ActionPlanState, EnrichState
from tools.enrich import WRITE_TOOLS


def entry(state: EnrichState):
    return "approval" if state.get("pending") else "model"


def after_model(state: EnrichState):
    call = state.get("tool_call")
    if call is None:
        return END
    if call["name"] == "enrich_note":
        return "metadata_context"
    if call["name"] == "create_reminder":
        return "reminder_model"
    return "pending_write" if call["name"] in WRITE_TOOLS else "read_tool"


def after_read(state: EnrichState):
    return "final" if state.get("steps", 0) >= config.ENRICH_AGENT_MAX_STEPS else "model"


def after_reminder_validation(state: EnrichState):
    return "pending_write" if state.get("action") else "final"


def after_plan_model(state: ActionPlanState):
    call = state.get("tool_call")
    if call is None:
        return END
    if call["name"] == "enrich_note":
        return "metadata_context"
    return "validate_write" if call["name"] in WRITE_TOOLS else "plan_read"


def after_plan_read(state: ActionPlanState):
    return END if state.get("steps", 0) >= config.ENRICH_AGENT_MAX_STEPS else "plan_model"


def after_validation(state: ActionPlanState):
    if state.get("action") or state.get("steps", 0) >= config.ENRICH_AGENT_MAX_STEPS:
        return END
    return "plan_model"
