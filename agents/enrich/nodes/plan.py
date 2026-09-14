"""Plan node: one planning model step for the action-plan graph.

Chooses a single write tool from a typed handoff (or finishes with no action).
Unlike `reason` it produces no user-facing answer. Single public `run`.
"""

import json
import logging

import config
from agents.runtime import model_gateway
from agents.enrich.state import ActionPlanState

logger = logging.getLogger(__name__)


def _build_request(messages: list[dict], tool_specs: list[dict]) -> dict:
    return {
        "model": config.ENRICH_AGENT_MODEL,
        "messages": messages,
        "temperature": 0,
        "tools": tool_specs,
        "tool_choice": "auto",
        "parallel_tool_calls": False,
    }


def _create_assistant_message(message) -> dict:
    data = {
        "role": "assistant",
        "content": message.content,
    }

    if message.tool_calls:
        data["tool_calls"] = [{
            "id": call.id,
            "type": "function",
            "function": {
                "name": call.function.name,
                "arguments": call.function.arguments,
            },
        } for call in message.tool_calls]

    return data


def _extract_first_tool(message) -> dict | None:
    if not message.tool_calls:
        return None

    tool_call = message.tool_calls[0]

    try:
        args = json.loads(tool_call.function.arguments or "{}")
    except Exception:
        args = {}

    return {
        "id": tool_call.id,
        "name": tool_call.function.name,
        "args": args,
    }


def run(state: ActionPlanState) -> dict:
    messages = state.get("messages") or []
    steps = state.get("steps", 0)

    try:
        model_request = _build_request(messages, state.get("tool_specs") or [])
        model_response = model_gateway.chat_completion(**model_request)
    except model_gateway.ModelGatewayError as exc:
        logger.warning("Enrich planning model call failed: %s", exc.kind)

        return {
            "messages": messages,
            "tool_call": None,
            "steps": steps + 1,
            "action": None,
            "model_error": exc.kind,
        }

    message = model_response.choices[0].message

    return {
        "messages": [*messages, _create_assistant_message(message)],
        "tool_call": _extract_first_tool(message),
        "steps": steps + 1,
        "action": None,
    }
