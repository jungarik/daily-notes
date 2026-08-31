"""The chat agent loop (planning).

A bounded ReAct-style tool-calling loop. Each step the model makes at most one
tool call (`parallel_tool_calls=False`). Read tools run inline. The one write
path is the `perform_action` HANDOFF tool: the loop hands the instruction to the
enrich (action) agent to plan a concrete write, then pauses for the user's
confirmation instead of executing it.

Returns a dict:
- {"status": "answer", "reply": str, "messages": [...]}
- {"status": "confirm", "action": {...}, "pending": {...}, "messages": [...]}
`messages` is the running provider message list, persisted so the thread (and a
paused action) can resume on the next request.
"""

import json
import logging

import config
import openai_client
from agents.chat.tools import TOOL_SPECS, HANDOFF_TOOLS, execute_tool
from agents.enrich import service as enrich_service

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
    """Drive the tool-calling loop until the model answers, a handed-off action
    needs confirmation, or the step budget is exhausted."""
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

        if name in HANDOFF_TOOLS:
            instruction = (args.get("instruction") or "").strip()
            action = enrich_service.plan_action(
                ctx.user_id, instruction, ctx.now, ctx.tz, ctx.locale)
            if not action:
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": "No concrete action could be determined."})
                continue
            pending = {"tool_call_id": tc.id, "action": action, "summary": action["summary"]}
            logger.info("chat handing off to enrich: %s user=%s", action["name"], ctx.user_id)
            return {"status": "confirm", "action": action, "pending": pending, "messages": messages}

        result = execute_tool(ctx, name, args)
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})

    # Budget exhausted — ask for a final answer with tools off.
    reply = (_complete(messages, use_tools=False).choices[0].message.content
             or "I couldn't finish that in time.")
    messages.append({"role": "assistant", "content": reply})
    return {"status": "answer", "reply": reply, "messages": messages}


def resume_action(ctx, messages: list, pending: dict, approve: bool) -> dict:
    """Provide the handed-off action's result (executed by the enrich agent, or
    declined) and continue the loop to a final reply."""
    if approve:
        result = enrich_service.execute_action(
            ctx.user_id, pending["action"], ctx.now, ctx.tz, ctx.locale)
    else:
        result = "The user declined this action; do not perform it. Acknowledge and continue."
    messages.append({"role": "tool", "tool_call_id": pending["tool_call_id"], "content": str(result)})
    return run_loop(ctx, messages)
