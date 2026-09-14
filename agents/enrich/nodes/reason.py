"""Reason node: one interactive Enrich model step.

Decides the next move — a read tool, a write proposal, or an answer. Once the
step budget is spent it makes a final tool-free call, so the model must answer
instead of looping (this replaces a separate `final` node). Single public `run`.
"""

import json
import logging

import config
from agents.runtime import model_gateway
from agents.enrich.state import EnrichState
from tools.enrich import TOOL_SPECS

logger = logging.getLogger(__name__)

_UNAVAILABLE_REPLY = (
    "I couldn't reach the AI provider right now. Please try again in a moment."
)


def _build_request(messages: list[dict], use_tools: bool) -> dict:
    model_request = {
        "model": config.ENRICH_AGENT_MODEL,
        "messages": messages,
        "temperature": 0.2,
    }

    if use_tools:
        model_request.update(
            tools=TOOL_SPECS,
            tool_choice="auto",
            parallel_tool_calls=False,
        )

    return model_request


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


def _unavailable(messages: list[dict], steps: int, kind: str) -> dict:
    return {
        "messages": [
            *messages,
            {"role": "assistant", "content": _UNAVAILABLE_REPLY},
        ],
        "steps": steps + 1,
        "tool_call": None,
        "status": "answer",
        "reply": _UNAVAILABLE_REPLY,
        "pending": None,
        "model_error": kind,
    }


def run(state: EnrichState) -> dict:
    messages = state.get("messages") or []
    steps = state.get("steps", 0)
    use_tools = steps < config.ENRICH_AGENT_MAX_STEPS

    try:
        model_request = _build_request(messages, use_tools)
        model_response = model_gateway.chat_completion(**model_request).choices[0].message
    except model_gateway.ModelGatewayError as exc:
        logger.warning("Enrich model call failed: %s", exc.kind)

        return _unavailable(messages, steps, exc.kind)

    tool_call = _extract_first_tool(model_response) if use_tools else None
    state_update = {
        "messages": [*messages, _create_assistant_message(model_response)],
        "steps": steps + 1,
        "tool_call": tool_call,
    }

    if tool_call is None:
        state_update.update(
            status="answer",
            reply=model_response.content or "",
            pending=None,
        )

    return state_update
