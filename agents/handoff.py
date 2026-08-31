"""Typed, serializable context passed from Chat to specialist agents."""

import json
from typing import TypedDict


class HandoffContract(TypedDict):
    instruction: str
    conversation_summary: str
    referenced_note_ids: list[int]
    citations: list[dict]
    resolved_entities: dict
    locale: str
    timezone: str | None
    now: str | None


def _tool_context(messages: list[dict]) -> tuple[list[int], list[dict]]:
    ids, names, results = [], {}, []
    for message in messages[-16:]:
        for tool_call in message.get("tool_calls") or []:
            names[tool_call.get("id")] = (tool_call.get("function") or {}).get("name")
            raw = (tool_call.get("function") or {}).get("arguments") or "{}"
            try:
                args = raw if isinstance(raw, dict) else json.loads(raw)
            except Exception:
                args = {}
            note_ids = args.get("note_ids") or []
            if not isinstance(note_ids, list):
                note_ids = [note_ids]
            values = [args.get("note_id"), *note_ids]
            for value in values:
                try:
                    ids.append(int(value))
                except (TypeError, ValueError):
                    pass
        if message.get("role") != "tool":
            continue
        tool_name = names.get(message.get("tool_call_id"))
        content = str(message.get("content") or "")
        results.append({"tool": tool_name, "content": content[:1000]})
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = None
        items = parsed if isinstance(parsed, list) else [parsed]
        for item in items:
            if not isinstance(item, dict):
                continue
            value = item.get("note_id")
            if value is None and tool_name in {"get_note", "neighbors"}:
                value = item.get("id")
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                pass
    return ids, results[-5:]


def _conversation_summary(messages: list[dict], limit: int = 4000) -> str:
    lines = []
    for message in messages[-16:]:
        role = message.get("role")
        content = message.get("content")
        if role not in {"user", "assistant"} or not content:
            continue
        lines.append(f"{role}: {' '.join(str(content).split())}")
    summary = "\n".join(lines)
    return summary[-limit:]


def build(messages: list[dict], tool_args: dict, citations: list[dict], ctx) -> HandoffContract:
    """Build ordered references from explicit args, prior tools, and citations."""
    ids = []
    for value in tool_args.get("referenced_note_ids") or []:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            pass
    tool_note_ids, tool_results = _tool_context(messages)
    ids.extend(tool_note_ids)
    ids.extend(item["note_id"] for item in citations if item.get("note_id") is not None)
    ordered_ids = list(dict.fromkeys(ids))
    cited = [{"note_id": int(item["note_id"]), "title": item.get("title") or "note"}
             for item in citations if item.get("note_id") is not None]
    resolved = dict(tool_args.get("resolved_entities") or {})
    resolved.update(
        last_note_id=ordered_ids[-1] if ordered_ids else None,
        ordinal_note_ids=ordered_ids,
        referenced_notes=cited,
        recent_tool_results=tool_results,
    )
    now = ctx.now.isoformat() if hasattr(ctx.now, "isoformat") else str(ctx.now or "")
    return {
        "instruction": str(tool_args.get("instruction") or "").strip(),
        "conversation_summary": _conversation_summary(messages),
        "referenced_note_ids": ordered_ids,
        "citations": cited,
        "resolved_entities": resolved,
        "locale": ctx.locale,
        "timezone": str(ctx.tz) if ctx.tz is not None else None,
        "now": now or None,
    }


def normalize(value, now=None, tz=None, locale: str = "en") -> HandoffContract:
    """Accept the typed contract or upgrade an older plain instruction."""
    if isinstance(value, dict):
        data = dict(value)
    else:
        data = {"instruction": str(value or "")}
    note_ids = []
    for note_id in data.get("referenced_note_ids") or []:
        try:
            note_ids.append(int(note_id))
        except (TypeError, ValueError):
            pass
    return {
        "instruction": str(data.get("instruction") or "").strip(),
        "conversation_summary": str(data.get("conversation_summary") or ""),
        "referenced_note_ids": note_ids,
        "citations": list(data.get("citations") or []),
        "resolved_entities": dict(data.get("resolved_entities") or {}),
        "locale": str(data.get("locale") or locale or "en"),
        "timezone": data.get("timezone") or (str(tz) if tz is not None else None),
        "now": data.get("now") or (now.isoformat() if hasattr(now, "isoformat") else None),
    }
