"""Reason node: one LLM planning step for the conversation graph.

Decides the next move — call a read tool, hand a write to a specialist, or
answer. Once the read-tool step budget is spent it makes a final tool-free call,
so the model must answer instead of looping. Pure of side effects; the only
public entry point is `run`.
"""

import json
import logging

import config
from agents.runtime import model_gateway
from agents.conversation.state import ChatState
from tools.conversation import TOOL_SPECS

logger = logging.getLogger(__name__)

_UNAVAILABLE_REPLY = (
    "I couldn't reach the AI provider right now. Please try again in a moment."
)


def _assistant_message(message) -> dict:
    data = {"role": "assistant", "content": message.content}

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


def _complete(messages: list[dict], use_tools: bool):
    kwargs = {
        "model": config.AGENT_MODEL,
        "messages": messages,
        "temperature": 0.2,
    }

    if use_tools:
        kwargs.update(
            tools=TOOL_SPECS,
            tool_choice="auto",
            parallel_tool_calls=False,
        )

    return model_gateway.chat_completion(**kwargs)


def _tool_call(message) -> dict | None:
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


def _unavailable(state: ChatState, kind: str) -> dict:
    return {
        "messages": [
            *state["messages"],
            {"role": "assistant", "content": _UNAVAILABLE_REPLY},
        ],
        "steps": state.get("steps", 0) + 1,
        "tool_call": None,
        "status": "answer",
        "reply": _UNAVAILABLE_REPLY,
        "pending": None,
        "trace": {**(state.get("trace") or {}), "model_error": kind},
    }


def run(state: ChatState) -> dict:
    use_tools = state.get("steps", 0) < config.AGENT_MAX_STEPS

    try:
        message = _complete(state["messages"], use_tools).choices[0].message
    except model_gateway.ModelGatewayError as exc:
        logger.warning("Conversation model call failed: %s", exc.kind)

        return _unavailable(state, exc.kind)

    call = _tool_call(message) if use_tools else None
    update = {
        "messages": [*state["messages"], _assistant_message(message)],
        "steps": state.get("steps", 0) + 1,
        "tool_call": call,
    }

    if call is None:
        update.update(status="answer", reply=message.content or "", pending=None)

    return update
