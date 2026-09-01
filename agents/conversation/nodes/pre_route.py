"""Cheap deterministic routing before the Conversation model."""

import json

from agents.conversation import domain
from agents.conversation.state import ChatState


def _latest_user_text(messages: list[dict]) -> str:
    for message in reversed(messages or []):
        if message.get("role") == "user":
            return message.get("content") or ""
    return ""


def run(state: ChatState) -> dict:
    text = _latest_user_text(state.get("messages") or [])
    if not domain.is_obvious_reminder_request(text):
        return {"pre_route": None}
    args = {"instruction": text}
    call = {
        "id": "pre-route-reminder",
        "name": "set_reminder",
        "args": args,
    }
    assistant = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": call["id"],
            "type": "function",
            "function": {
                "name": call["name"],
                "arguments": json.dumps(args, ensure_ascii=False),
            },
        }],
    }
    trace = {**(state.get("trace") or {})}
    trace["pre_route"] = "reminder"
    return {
        "messages": [*(state.get("messages") or []), assistant],
        "tool_call": call, 
        "pre_route": "reminder", 
        "trace": trace
      }
