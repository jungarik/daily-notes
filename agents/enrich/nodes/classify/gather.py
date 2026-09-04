"""classify_gather node: collect vault context + related notes for a note.

Runs the internal metadata-context tools (note text, existing paths/tags, vault
roots, related notes) and stashes them for the proposal step. Single public
`run`.
"""

import json
import time

from common import helper
from agents.contracts import ToolResult
from tools import enrich as tools
from agents.enrich.state import Ctx, context_to_dict
from agents.runtime.execute_tool import execute_allowed_tool


def _tool_text(result) -> str:
    if isinstance(result, ToolResult):
        return helper.json_text(result.data)

    return str(result)


def _user_id(state: dict) -> int:
    return int(state.get("user_id") or state["context"]["user_id"])


def _context(state: dict, user_id: int) -> Ctx:
    data = state.get("context") or {}

    return Ctx(user_id, data.get("now"), tz=data.get("tz"),
               locale=data.get("locale") or "en")


def _tool(ctx: Ctx, name: str, args: dict, trace: list[dict]):
    started = time.perf_counter()
    raw_result = execute_allowed_tool(
        tools.TOOLS,
        tools.METADATA_CONTEXT_TOOLS,
        context_to_dict(ctx),
        name,
        args,
        "enrich",
    )
    result = _tool_text(raw_result)
    latency_ms = round((time.perf_counter() - started) * 1000)
    error = None

    if isinstance(raw_result, ToolResult):
        error = raw_result.data.get("error")
    elif result.startswith("Error:") or result.startswith("Error running"):
        error = result

    if error:
        trace.append({"kind": "tool", "tool": name, "status": "error",
                      "latency_ms": latency_ms, "error": str(error)[:500]})
        raise RuntimeError(error)

    trace.append({"kind": "tool", "tool": name, "status": "ok",
                  "latency_ms": latency_ms})

    try:
        return json.loads(result)
    except json.JSONDecodeError:
        return result


def run(state: dict) -> dict:
    user_id = _user_id(state)
    ctx = _context(state, user_id)
    call = state.get("tool_call") or {}
    args = call.get("args") or {}
    note_id = state.get("metadata_note_id") or args.get("note_id")
    text = (state.get("metadata_text") or "").strip()
    trace = [*(state.get("metadata_trace") or [])]

    try:
        if not text and note_id is not None:
            note = _tool(ctx, "get_note_context", {"note_id": int(note_id)}, trace)
            text = ((note or {}).get("text") or "").strip()

        if not text:
            raise ValueError("note not found or empty")

        paths_data = _tool(ctx, "list_paths", {}, trace)
        tags_data = _tool(ctx, "list_tags", {}, trace)
        vault = _tool(ctx, "get_vault_context", {}, trace)
        related_data = _tool(ctx, "find_related_notes", {
            "text": text,
            "exclude_note_id": int(note_id) if note_id is not None else None,
        }, trace)
        paths = (
            paths_data.get("paths", paths_data)
            if isinstance(paths_data, dict)
            else paths_data
        )
        tags = (
            tags_data.get("tags", tags_data)
            if isinstance(tags_data, dict)
            else tags_data
        )
        related = (
            related_data.get("notes", related_data)
            if isinstance(related_data, dict)
            else related_data
        )
        known_paths = ([(item["path"], item["count"]) for item in paths]
                       if isinstance(paths, list) else [])
        known_tags = ([(item["tag"], item["count"]) for item in tags]
                      if isinstance(tags, list) else [])
        context = {
            "known_paths": known_paths, "known_tags": known_tags,
            "related_notes": related if isinstance(related, list) else [],
            "root_folders": vault["root_folders"],
            "default_root": vault["default_root"],
        }
    except Exception as exc:
        trace.append({
            "kind": "node",
            "node": "classify_gather",
            "status": "error",
            "error": str(exc)[:500],
        })

        return {
            "metadata_text": "",
            "metadata_note_id": note_id,
            "metadata_context": {},
            "metadata_error": str(exc),
            "metadata_trace": trace,
        }

    trace.append({
        "kind": "node",
        "node": "classify_gather",
        "status": "ok",
        "related_note_ids": [
            item.get("note_id")
            for item in context["related_notes"]
            if item.get("note_id") is not None
        ],
    })

    return {
        "metadata_text": text,
        "metadata_note_id": note_id,
        "metadata_context": context,
        "metadata_error": None,
        "metadata_trace": trace,
    }
