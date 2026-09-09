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
    extract_tool,
)
from agents.enrich.state import EnrichState
from tools.enrich import TOOL_SPECS

logger = logging.getLogger(__name__)


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


def run(state: EnrichState) -> dict:
    messages = state.get("messages") or []
    use_tools = state.get("steps", 0) < config.ENRICH_AGENT_MAX_STEPS

    try:
        model_request = _build_request(messages, use_tools)
        model_response = model_gateway.chat_completion(**model_request).choices[0].message

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
