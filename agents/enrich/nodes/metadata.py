"""Explicit metadata context, classification, and validation graph nodes."""

import json
import logging
import time

import config
from agents.enrich import domain
from agents.enrich.prompts import enrichment_prompt
from agents.enrich.tools import Ctx, execute_context_tool
from agents.runtime import model_gateway

logger = logging.getLogger(__name__)


def _user_id(state: dict) -> int:
    return int(state.get("user_id") or state["context"]["user_id"])


def _context(state: dict, user_id: int) -> Ctx:
    data = state.get("context") or {}
    return Ctx(user_id, data.get("now"), tz=data.get("tz"),
               locale=data.get("locale") or "en")


def _tool(ctx: Ctx, name: str, args: dict, trace: list[dict]):
    started = time.perf_counter()
    result = execute_context_tool(ctx, name, args)
    latency_ms = round((time.perf_counter() - started) * 1000)
    if result.startswith("Error:") or result.startswith("Error running"):
        trace.append({"kind": "tool", "tool": name, "status": "error",
                      "latency_ms": latency_ms, "error": result[:500]})
        raise RuntimeError(result)
    trace.append({"kind": "tool", "tool": name, "status": "ok",
                  "latency_ms": latency_ms})
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        return result


def load_context(state: dict) -> dict:
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

        paths = _tool(ctx, "list_paths", {}, trace)
        tags = _tool(ctx, "list_tags", {}, trace)
        vault = _tool(ctx, "get_vault_context", {}, trace)
        related = _tool(ctx, "find_related_notes", {
            "text": text, "exclude_note_id": int(note_id) if note_id is not None else None,
        }, trace)
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
        trace.append({"kind": "node", "node": "metadata_context",
                      "status": "error", "error": str(exc)[:500]})
        return {"metadata_text": "", "metadata_note_id": note_id,
                "metadata_context": {}, "metadata_error": str(exc),
                "metadata_trace": trace}
    trace.append({"kind": "node", "node": "metadata_context", "status": "ok",
                  "related_note_ids": [item.get("note_id")
                                       for item in context["related_notes"]
                                       if item.get("note_id") is not None]})
    return {"metadata_text": text, "metadata_note_id": note_id,
            "metadata_context": context, "metadata_error": None,
            "metadata_trace": trace}


def propose(state: dict) -> dict:
    trace = [*(state.get("metadata_trace") or [])]
    if state.get("metadata_error"):
        return {"raw_metadata": {}, "metadata_trace": trace}
    context = state["metadata_context"]
    try:
        system = enrichment_prompt(
            context["known_paths"], context["known_tags"],
            context["related_notes"], context["root_folders"],
            context["default_root"], config.ENRICH_SIMILAR_MAX_DISTANCE)
        response = model_gateway.chat_completion(
            model=config.ENRICH_LLM_MODEL, temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": state["metadata_text"]}],
        )
        raw = json.loads(response.choices[0].message.content)
        trace.append({"kind": "node", "node": "metadata_model", "status": "ok"})
        return {"raw_metadata": raw, "metadata_trace": trace}
    except Exception as exc:
        logger.exception("Metadata proposal failed; using normalized fallback")
        trace.append({"kind": "node", "node": "metadata_model", "status": "error",
                      "error": type(exc).__name__})
        return {"raw_metadata": {}, "metadata_error": str(exc),
                "metadata_trace": trace}


def validate(state: dict) -> dict:
    context = state.get("metadata_context") or {}
    metadata = domain.normalize(
        state.get("raw_metadata") or {}, state.get("metadata_text") or "",
        context.get("root_folders"), context.get("default_root"))
    trace = [*(state.get("metadata_trace") or []),
             {"kind": "node", "node": "metadata_validation", "status": "ok"}]
    update = {"metadata": metadata, "metadata_trace": trace}
    call = state.get("tool_call")
    if call and call.get("name") == "enrich_note":
        update["tool_call"] = {
            **call, "args": {**(call.get("args") or {}), **metadata},
        }
    return update
