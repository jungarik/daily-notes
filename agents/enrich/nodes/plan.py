"""Plan node: one planning model step for the action-plan graph.

Chooses a single write tool from a typed handoff (or finishes with no action).
Unlike `reason` it produces no user-facing answer. Single public `run`.
"""

import logging

import config
from agents.runtime import model_gateway
from agents.enrich.nodes._llm import assistant_message, extract_tool
from agents.enrich.state import ActionPlanState

logger = logging.getLogger(__name__)


def run(state: ActionPlanState) -> dict:
    try:
        model_response = model_gateway.chat_completion(
            model=config.ENRICH_AGENT_MODEL,
            messages=state.get("messages") or [],
            temperature=0,
            tools=state.get("tool_specs") or [],
            tool_choice="auto",
            parallel_tool_calls=False,
        )
    except model_gateway.ModelGatewayError as exc:
        logger.warning("Enrich planning model call failed: %s", exc.kind)

        return {
            "messages": state.get("messages") or [],
            "tool_call": None,
            "steps": state.get("steps", 0) + 1,
            "action": None,
            "model_error": exc.kind,
        }

    message = model_response.choices[0].message
    messages = state.get("messages") or []
    
    return {
        "messages": [*messages, assistant_message(message)],
        "tool_call": extract_tool(message),
        "steps": state.get("steps", 0) + 1,
        "action": None,
    }
