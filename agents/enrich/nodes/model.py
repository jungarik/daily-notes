"""LLM nodes and message parsing for Enrich workflows."""

import json

import config
import openai_client
from agents.enrich.state import ActionPlanState, EnrichState
from agents.enrich.tools import TOOL_SPECS


def assistant_dict(msg) -> dict:
    data = {"role": "assistant", "content": msg.content}
    if msg.tool_calls:
        data["tool_calls"] = [{
            "id": call.id, "type": "function",
            "function": {"name": call.function.name,
                         "arguments": call.function.arguments},
        } for call in msg.tool_calls]
    return data


def parse_tool_call(msg) -> dict | None:
    if not msg.tool_calls:
        return None
    call = msg.tool_calls[0]
    try:
        args = json.loads(call.function.arguments or "{}")
    except Exception:
        args = {}
    return {"id": call.id, "name": call.function.name, "args": args}


def complete(messages, use_tools):
    kwargs = {"model": config.ENRICH_AGENT_MODEL,
              "messages": messages, "temperature": 0.2}
    if use_tools:
        kwargs.update(
          tools=TOOL_SPECS,
          tool_choice="auto",
          parallel_tool_calls=False
        )
    return openai_client.get_client().chat.completions.create(**kwargs)


def run(state: EnrichState) -> dict:
    msg = complete(state["messages"], use_tools=True).choices[0].message
    call = parse_tool_call(msg)
    update = {"messages": [*state["messages"], assistant_dict(msg)],
              "steps": state.get("steps", 0) + 1, "tool_call": call}
    if call is None:
        update.update(status="answer", reply=msg.content or "", pending=None)
    return update


def plan(state: ActionPlanState) -> dict:
    response = openai_client.get_client().chat.completions.create(
        model=config.ENRICH_AGENT_MODEL, 
        messages=state["messages"],
        temperature=0, 
        tools=state["tool_specs"], 
        tool_choice="auto",
        parallel_tool_calls=False,
    )
    msg = response.choices[0].message
    return {"messages": [*state["messages"], assistant_dict(msg)],
            "tool_call": parse_tool_call(msg),
            "steps": state.get("steps", 0) + 1, "action": None}
