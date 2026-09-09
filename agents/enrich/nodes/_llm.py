"""Shared LLM helpers for the Enrich reasoning/planning nodes.

Not a graph node — just the OpenAI call plumbing used by `reason` and `plan`.
"""

import json

UNAVAILABLE_REPLY = (
    "I couldn't reach the AI provider right now. Please try again in a moment."
)


def assistant_message(message) -> dict:
    data = {
      "role": "assistant", 
      "content": message.content}

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


def extract_tool(message) -> dict | None:
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
