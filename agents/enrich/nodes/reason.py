"""Reason node: one interactive Enrich model step.

Decides the next move — a read tool, a write proposal, or an answer. Once the
step budget is spent it makes a final tool-free call, so the model must answer
instead of looping (this replaces a separate `final` node). Single public `run`.
"""

import logging

import config
from agents.runtime import model_gateway
from agents.enrich.nodes._llm import (
    UNAVAILABLE_REPLY,
    assistant_message,
    complete,
    extract_tool,
)
from agents.enrich.state import EnrichState

logger = logging.getLogger(__name__)


def _unavailable(state: EnrichState, kind: str) -> dict:
    return {
        "messages": [
            *state.get("messages", []),
            {"role": "assistant", "content": UNAVAILABLE_REPLY},
        ],
        "steps": state.get("steps", 0) + 1,
        "tool_call": None,
        "status": "answer",
        "reply": UNAVAILABLE_REPLY,
        "pending": None,
        "model_error": kind,
    }


def run(state: EnrichState) -> dict:
    messages = state.get("messages") or []
    use_tools = state.get("steps", 0) < config.ENRICH_AGENT_MAX_STEPS

    try:
        model_response = complete(messages, use_tools).choices[0].message

    except model_gateway.ModelGatewayError as exc:
        logger.warning("Enrich model call failed: %s", exc.kind)

        return {
            "messages": [
                *state.get("messages", []),
                {"role": "assistant", "content": UNAVAILABLE_REPLY},
            ],
            "steps": state.get("steps", 0) + 1,
            "tool_call": None,
            "status": "answer",
            "reply": UNAVAILABLE_REPLY,
            "pending": None,
            "model_error": exc.kind}


    tool_call = extract_tool(model_response) if use_tools else None
    update = {
        "messages": [*messages, assistant_message(model_response)],
        "steps": state.get("steps", 0) + 1,
        "tool_call": tool_call,
    }

    if tool_call is None:
        update.update(status="answer", reply=model_response.content or "", pending=None)

    return update
