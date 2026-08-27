"""The agent loop (planning).

A bounded ReAct-style tool-calling loop. Each step the model makes at most one
tool call (`parallel_tool_calls=False`), which keeps the write-confirmation
protocol simple: a write pauses the loop cleanly with a single pending call.

Returns a dict:
- {"status": "answer", "reply": str, "messages": [...]}
- {"status": "confirm", "action": {...}, "pending": {...}, "messages": [...]}
`messages` is the running provider message list, persisted so the thread (and a
paused write) can resume on the next request.
"""

import json
import logging

import config
import openai_client
from agents.chat.tools import TOOL_SPECS, WRITE_TOOLS, execute_tool, summarize_write

logger = logging.getLogger(__name__)


def _assistant_dict(msg) -> dict:
    """Serialize an OpenAI assistant message (possibly with a tool call) to the
    plain-dict form we both persist and send back on the next call."""
    d = {"role": "assistant", "content": msg.content}
    if msg.tool_calls:
        d["tool_calls"] = [{
            "id": tc.id, "type": "function",
            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
        } for tc in msg.tool_calls]
    return d


def _complete(messages, use_tools):
    kwargs = {"model": config.AGENT_MODEL, "messages": messages, "temperature": 0.2}
    if use_tools:
        kwargs.update(tools=TOOL_SPECS, tool_choice="auto", parallel_tool_calls=False)
    return openai_client.get_client().chat.completions.create(**kwargs)


def run_loop(ctx, messages: list) -> dict:
    """Drive the tool-calling loop until the model answers, a write needs
    confirmation, or the step budget is exhausted."""
    for step in range(config.AGENT_MAX_STEPS):
        msg = _complete(messages, use_tools=True).choices[0].message
        messages.append(_assistant_dict(msg))

        if not msg.tool_calls:
            return {"status": "answer", "reply": msg.content or "", "messages": messages}

        tc = msg.tool_calls[0]   # parallel_tool_calls=False → at most one
        name = tc.function.name
        try:
            args = json.loads(tc.function.arguments or "{}")
        except Exception:
            args = {}

        if name in WRITE_TOOLS:
            pending = {"tool_call_id": tc.id, "name": name, "args": args,
                       "summary": summarize_write(name, args)}
            logger.info("agent pausing for confirmation: %s user=%s", name, ctx.user_id)
            return {"status": "confirm",
                    "action": {"name": name, "args": args, "summary": pending["summary"]},
                    "pending": pending, "messages": messages}

        result = execute_tool(ctx, name, args)
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})

    # Budget exhausted — ask for a final answer with tools off.
    reply = (_complete(messages, use_tools=False).choices[0].message.content
             or "I couldn't finish that in time.")
    messages.append({"role": "assistant", "content": reply})
    return {"status": "answer", "reply": reply, "messages": messages}


def resume_write(ctx, messages: list, pending: dict, approve: bool) -> dict:
    """Provide the paused write's tool result (executed or declined) and continue."""
    if approve:
        result = execute_tool(ctx, pending["name"], pending["args"])
    else:
        result = "The user declined this action; do not perform it. Acknowledge and continue."
    messages.append({"role": "tool", "tool_call_id": pending["tool_call_id"], "content": str(result)})
    return run_loop(ctx, messages)
