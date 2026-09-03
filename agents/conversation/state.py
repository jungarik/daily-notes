"""State and serialization helpers for the conversation graph."""

from datetime import datetime
from typing import Literal, TypedDict
from zoneinfo import ZoneInfo

from agents.contracts import ToolResult


class ConversationContext:
    """User-scoped clock, citations, and trace for one conversation turn."""

    def __init__(self, user_id: int, now, tz=None, locale: str = "en"):
        self.user_id = user_id
        self.now = now
        self.tz = tz
        self.locale = locale
        self.citations: list[dict] = []
        self._cited: set[int] = set()
        self.trace: dict = {"tools": [], "retrieved_chunks": [], "routes": []}

    def cite(self, note_id: int, title: str, path=None, date=None) -> None:
        if note_id not in self._cited:
            self._cited.add(note_id)
            self.citations.append({
                "note_id": note_id,
                "title": title or "note",
                "path": path,
                "date": date,
            })

    def record_tool(self, name: str, args: dict, result=None) -> None:
        self.trace["tools"].append({
            "name": name,
            "args": args or {},
            "result": str(result)[:1000] if result is not None else None,
        })

    def record_route(self, route: str) -> None:
        self.trace["routes"].append(route)


Ctx = ConversationContext


class ChatState(TypedDict, total=False):
    messages: list[dict]
    context: dict
    citations: list[dict]
    reference_notes: list[dict]
    trace: dict
    steps: int
    tool_call: dict | None
    status: Literal["answer", "confirm"]
    reply: str
    action: dict | None
    pending: dict | None
    completed_action_id: str | None


def _context_to_dict(ctx: Ctx) -> dict:
    return {
        "user_id": ctx.user_id,
        "now": ctx.now.isoformat() if hasattr(ctx.now, "isoformat") else ctx.now,
        "tz": str(ctx.tz),
        "locale": ctx.locale,
    }


def tool_context(ctx: Ctx) -> dict:
    return {
        "user_id": ctx.user_id,
        "tz": ctx.tz,
    }


def apply_tool_result(ctx: Ctx, result: ToolResult) -> None:
    for citation in result.citations:
        ctx.cite(
            citation["note_id"],
            citation.get("title") or "note",
            citation.get("path"),
            citation.get("date"),
        )

    if result.retrieved_chunks:
        ctx.trace.setdefault("retrieved_chunks", []).extend(result.retrieved_chunks)


def _restore(value, factory):
    try:
        return factory(value)
    except Exception:
        return value


def context_from_state(state: ChatState) -> Ctx:
    data = state["context"]
    ctx = Ctx(data["user_id"], _restore(data.get("now"), datetime.fromisoformat),
              tz=_restore(data.get("tz"), ZoneInfo),
              locale=data.get("locale") or "en")
    ctx.citations = list(state.get("citations") or [])
    ctx._cited = {item["note_id"] for item in ctx.citations}
    ctx.trace = dict(state.get("trace") or {
        "tools": [], "retrieved_chunks": [], "routes": [],
    })
    return ctx


def context_update(ctx: Ctx) -> dict:
    return {"citations": ctx.citations, "trace": ctx.trace}


def initial_state(ctx: Ctx, messages: list, pending: dict | None = None,
                  reference_notes: list[dict] | None = None) -> ChatState:
    return {
        "context": _context_to_dict(ctx), "messages": list(messages), "steps": 0,
        "tool_call": None, "pending": pending,
        "action": pending.get("action") if pending else None,
        "completed_action_id": None, "citations": [],
        "reference_notes": list(reference_notes or []),
        "trace": {"tools": [], "retrieved_chunks": [], "routes": []},
    }


def merge_references(existing: list[dict], current: list[dict]) -> list[dict]:
    merged = list(existing)
    for citation in current:
        merged = [item for item in merged
                  if item.get("note_id") != citation.get("note_id")]
        merged.append(citation)
    return merged[-20:]
