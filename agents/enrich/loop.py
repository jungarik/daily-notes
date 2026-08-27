"""The enrichment agent loop.

Bounded single-tool-call loop (mirrors the chat agent): the model may call read
tools to gather vocabulary/context, then calls `submit_metadata` to emit its
final structured classification, which ends the run. Returns the normalized
metadata dict, or None if it didn't converge (the caller then falls back to the
one-shot enricher).
"""

import json
import logging

import config
import openai_client
from agents.enrich.tools import TOOL_SPECS, TERMINAL_TOOL, execute_tool

logger = logging.getLogger(__name__)


def _assistant_dict(msg) -> dict:
    d = {"role": "assistant", "content": msg.content}
    if msg.tool_calls:
        d["tool_calls"] = [{
            "id": tc.id, "type": "function",
            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
        } for tc in msg.tool_calls]
    return d


def run_loop(ctx, messages: list):
    """Drive the loop until the agent submits metadata or the step budget runs
    out. Returns the metadata dict or None."""
    client = openai_client.get_client()
    for step in range(config.ENRICH_AGENT_MAX_STEPS):
        # On the last allowed step, force the terminal tool so we always get a
        # structured result rather than a stray text message.
        force = step == config.ENRICH_AGENT_MAX_STEPS - 1
        resp = client.chat.completions.create(
            model=config.ENRICH_AGENT_MODEL, messages=messages, temperature=0,
            tools=TOOL_SPECS, parallel_tool_calls=False,
            tool_choice=({"type": "function", "function": {"name": TERMINAL_TOOL}}
                         if force else "auto"),
        )
        msg = resp.choices[0].message
        messages.append(_assistant_dict(msg))
        if not msg.tool_calls:
            continue   # a stray text turn — let the loop nudge toward submit
        tc = msg.tool_calls[0]
        try:
            args = json.loads(tc.function.arguments or "{}")
        except Exception:
            args = {}
        result = execute_tool(ctx, tc.function.name, args)
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})
        if tc.function.name == TERMINAL_TOOL and ctx.result is not None:
            return ctx.result
    return None
