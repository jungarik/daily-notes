"""Conditional edges for the enricher workflow.

Action-plan graph (stateless):

    START ────────────────▶ plan
    plan ─after_plan──────▶ act | classify_gather | link_context |
                            validate_write | END
    act ─after_plan_read──▶ plan | END
    classify_gather ▶ classify_propose ▶ classify_normalize ▶ validate_write
    link_context ─────────▶ validate_write
    validate_write ─after_validation─▶ plan | END

It loops back to `plan` until an action is produced or the step budget runs
out. There is no pause in here: the agent returns `needs_input` and the farm's
loop owns the confirmation.
"""

from langgraph.graph import END

import config
from agents.enricher.state import ActionPlanState
from tools.enricher import WRITE_TOOLS


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
