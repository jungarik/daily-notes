"""gather node: collect the note and the vault vocabulary it is filed against.

Runs the context tools — the note's text, the user's existing paths and tags,
the localised root folders, and the notes nearest this one as classification
precedent — and stashes them for `propose`. `run` makes every tool call and
threads an immutable trace through the pure helpers below. Single public `run`.
"""

import json
import time

from agents.classifier.state import ClassifyState, context_from_state
from agents.contracts import ToolResult, build_context, restore_clock
from agents.runtime.execute_tool import execute_allowed_tool
from common import helper
from tools import classifier as tools

NAME = "classifier"

_EMPTY_NOTE = "note not found or empty"


def _tool_context(state: ClassifyState) -> dict:
    """The context these tools run under.

    One entry shape now. Inside the enricher this rebuilt a context from either
    `user_context` or a bare `user_id`, because the metadata pipeline was
    entered two ways; the agent has one `start`, so there is one shape.
    """
    context = context_from_state(state)
    now, tz, locale = restore_clock(context)

    return build_context(context["user_id"], now, tz=tz, locale=locale)


def _tool_text(result) -> str:
    if isinstance(result, ToolResult):
        return helper.json_text(result.data)

    return str(result)


def _tool_error(result, text: str) -> str | None:
    if isinstance(result, ToolResult):
        return result.data.get("error")

    if text.startswith("Error:") or text.startswith("Error running"):
        return text

    return None


def _parsed(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _trace_tool(trace: list[dict], name: str, latency_ms: int,
                error: str | None) -> list[dict]:
    if error:
        return [*trace, {"kind": "tool", "tool": name, "status": "error",
                         "latency_ms": latency_ms, "error": str(error)[:500]}]

    return [*trace, {"kind": "tool", "tool": name, "status": "ok",
                     "latency_ms": latency_ms}]


def _context_calls(text: str, note_id) -> tuple:
    """The context tools to run, in order, once the note text is known."""
    return (
        ("list_paths", {}),
        ("list_tags", {}),
        ("get_vault_context", {}),
        ("find_related_notes", {
            "text": text,
            "exclude_note_id": int(note_id) if note_id is not None else None,
        }),
    )


def _unwrapped(data, key: str):
    return data.get(key, data) if isinstance(data, dict) else data


def _counted(items, key: str) -> list[tuple]:
    if not isinstance(items, list):
        return []

    return [(item[key], item["count"]) for item in items]


def _build_context(collected: dict) -> dict:
    vault = collected["get_vault_context"]
    related = _unwrapped(collected["find_related_notes"], "notes")

    return {
        "known_paths": _counted(_unwrapped(collected["list_paths"], "paths"), "path"),
        "known_tags": _counted(_unwrapped(collected["list_tags"], "tags"), "tag"),
        "related_notes": related if isinstance(related, list) else [],
        "root_folders": vault["root_folders"],
        "default_root": vault["default_root"],
    }


def _failed(note_id, trace: list[dict], error: str) -> dict:
    return {
        "text": "",
        "note_id": note_id,
        "context": {},
        "error": error,
        "trace": [*trace, {
            "kind": "node",
            "node": "gather",
            "status": "error",
            "error": str(error)[:500],
        }],
    }


def _gathered(text: str, note_id, context: dict, trace: list[dict]) -> dict:
    return {
        "text": text,
        "note_id": note_id,
        "context": context,
        "error": None,
        "trace": [*trace, {
            "kind": "node",
            "node": "gather",
            "status": "ok",
            "related_note_ids": [
                item.get("note_id")
                for item in context["related_notes"]
                if item.get("note_id") is not None
            ],
        }],
    }


def run(state: ClassifyState) -> dict:
    context = _tool_context(state)
    note_id = state.get("note_id")
    text = (state.get("text") or "").strip()
    trace = list(state.get("trace") or [])

    if not text and note_id is not None:
        started = time.perf_counter()
        result = execute_allowed_tool(
            tools.TOOLS,
            tools.CONTEXT_TOOLS,
            context,
            "get_note_context",
            {"note_id": int(note_id)},
            NAME,
        )
        result_text = _tool_text(result)
        error = _tool_error(result, result_text)
        trace = _trace_tool(trace, "get_note_context",
                            round((time.perf_counter() - started) * 1000), error)

        if error:
            return _failed(note_id, trace, error)

        text = ((_parsed(result_text) or {}).get("text") or "").strip()

    if not text:
        return _failed(note_id, trace, _EMPTY_NOTE)

    collected = {}

    for name, tool_args in _context_calls(text, note_id):
        started = time.perf_counter()
        result = execute_allowed_tool(
            tools.TOOLS,
            tools.CONTEXT_TOOLS,
            context,
            name,
            tool_args,
            NAME,
        )
        result_text = _tool_text(result)
        error = _tool_error(result, result_text)
        trace = _trace_tool(trace, name,
                            round((time.perf_counter() - started) * 1000), error)

        if error:
            return _failed(note_id, trace, error)

        collected[name] = _parsed(result_text)

    try:
        gathered_context = _build_context(collected)
    except Exception as exc:
        return _failed(note_id, trace, str(exc))

    return _gathered(text, note_id, gathered_context, trace)
