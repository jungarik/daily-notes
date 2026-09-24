"""Conditional edges for the enricher workflows.

Interactive graph (capture loop):

    START ─entry──▶ reason | approve
    reason ─after_reason─▶ act | classify_gather | link_context | stage | END
    act ──────────────────▶ reason
    classify_gather ▶ classify_propose ▶ classify_normalize ▶ stage
    link_context ─────────▶ stage
    stage ────────────────▶ approve ─▶ reason

Action-plan graph (stateless): plan ─▶ act | classify_* | link_context |
validate_write, looping back to plan until an action is produced.
"""

from langgraph.graph import END

import config
from agents.enricher.state import ActionPlanState, EnrichState
from tools.enricher import WRITE_TOOLS


def entry(state: EnrichState):
    return "approve" if state.get("pending") else "reason"


def after_reason(state: EnrichState):
    tool_call = state.get("tool_call")

    if tool_call is None:
        return END

    if tool_call["name"] == "enrich_note":
        return "classify_gather"

    if tool_call["name"] == "link_notes":
        return "link_context"

    return "stage" if tool_call["name"] in WRITE_TOOLS else "act"


def after_plan(state: ActionPlanState):
    call = state.get("tool_call")

    if call is None:
        return END

    if call["name"] == "enrich_note":
        return "classify_gather"

    if call["name"] == "link_notes":
        return "link_context"

    return "validate_write" if call["name"] in WRITE_TOOLS else "act"


def after_plan_read(state: ActionPlanState):
    return END if state.get("steps", 0) >= config.ENRICH_AGENT_MAX_STEPS else "plan"


def after_validation(state: ActionPlanState):
    if state.get("action") or state.get("steps", 0) >= config.ENRICH_AGENT_MAX_STEPS:
        return END

    return "plan"
