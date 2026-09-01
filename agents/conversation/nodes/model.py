"""LLM planning node for the conversation graph."""

import json

import config
import openai_client
from agents.conversation.state import ChatState
from agents.conversation.tools import TOOL_SPECS


def assistant_dict(msg) -> dict:
    data = {"role": "assistant", "content": msg.content}
    if msg.tool_calls:
        data["tool_calls"] = [{
            "id": tc.id, "type": "function",
            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
        } for tc in msg.tool_calls]
    return data


def complete(messages, use_tools):
    kwargs = {"model": config.AGENT_MODEL, "messages": messages, "temperature": 0.2}
    if use_tools:
        kwargs.update(tools=TOOL_SPECS, tool_choice="auto", parallel_tool_calls=False)
    return openai_client.get_client().chat.completions.create(**kwargs)


def parse_tool_call(msg) -> dict | None:
    if not msg.tool_calls:
        return None
    tc = msg.tool_calls[0]
    try:
        args = json.loads(tc.function.arguments or "{}")
    except Exception:
        args = {}
    return {"id": tc.id, "name": tc.function.name, "args": args}


def run(state: ChatState) -> dict:
    msg = complete(state["messages"], use_tools=True).choices[0].message
    messages = [*state["messages"], assistant_dict(msg)]
    call = parse_tool_call(msg)
    update = {
      "messages": messages, 
      "steps": state.get("steps", 0) + 1,
      "tool_call": call
    }
    if call is None:
        update.update(status="answer", reply=msg.content or "", pending=None)
    return update
