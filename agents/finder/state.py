"""State and serialization helpers for the finder graph.

Trimmed from the conversation controller's state: the farm owns the approval
pause, so there is no `pending`, no staged `action`, and no
`completed_action_id` here. What is left is one read-and-answer turn — the
clock, the citations it gathered, and the trace.

The clock is `UserContext`, the one contract every agent uses; this module adds
only what is finder's own. Citations and the trace are **state channels**, not fields on that
context: they accumulate, and a node that accumulates by mutating an object it
was handed is using mutation as an output channel. The helpers below take the
current value and return the next one, so `act.py` can put them in its patch
like every other field.
"""

from typing import TypedDict

from agents.contracts import ToolResult, UserContext, restore_clock


class FinderState(TypedDict, total=False):
    messages: list[dict]
    context: dict
    citations: list[dict]
    retrieved_chunks: list[dict]
    reference_notes: list[dict]
    trace: dict
    steps: int
    tool_call: dict | None
    reply: str


def context_from_state(state: FinderState) -> UserContext:
    """The context this graph's state carries, under this graph's key."""
    return state.get("context") or {}


def tool_context(context: UserContext) -> dict:
    """What a finder tool is scoped by: the owner, and the clock `list_agenda`
    resolves a range against.

    The timezone is restored to a live `ZoneInfo` here because that is what the
    tool needs; the rest of the context is not passed on. Narrower than the
    context on purpose — a read tool has no use for the locale, and handing it
    one invites it to localise something the responder owns.
    """
    _, tz, _ = restore_clock(context)

    return {
        "user_id": context["user_id"],
        "tz": tz,
    }


def merge_citations(existing: list[dict], fresh: list[dict]) -> list[dict]:
    """`existing` plus the citations it does not already hold, first one wins.

    A turn cites the same note from two tools often — a search hit that is then
    read, or a neighbour that also matched. The first citation is kept because
    it is the one whose title and path the answer was written against.
    """
    seen = {item["note_id"] for item in existing}
    merged = list(existing)

    for citation in fresh:
        note_id = citation.get("note_id")

        if note_id is None or note_id in seen:
            continue

        seen.add(note_id)
        merged.append({
            "note_id": note_id,
            "title": citation.get("title") or "note",
            "path": citation.get("path"),
            "date": citation.get("date"),
        })

    return merged


def record_tool(trace: dict, name: str, args: dict, result=None) -> dict:
    """`trace` with one tool call appended.

    The result is clipped: a trace is for reading back what happened, and a
    tool that returns a whole note would otherwise make the record larger than
    the answer it explains.
    """
    tools = [*(trace.get("tools") or []), {
        "name": name,
        "args": args or {},
        "result": str(result)[:1000] if result is not None else None,
    }]

    return {**trace, "tools": tools}


def record_route(trace: dict, route: str) -> dict:
    """`trace` with one route appended."""
    return {**trace, "routes": [*(trace.get("routes") or []), route]}


def merge_chunks(existing: list[dict], fresh: list) -> list[dict]:
    """`existing` plus the chunks this tool retrieved.

    A channel of its own rather than a corner of `trace`: the matched text is
    evidence a later agent plans and answers from, while `trace` is a record of
    what ran. Burying one inside the other meant a reader had to take the debug
    blob to reach the evidence.
    """
    if not fresh:
        return existing

    return [*existing, *fresh]


def apply_tool_result(citations: list[dict], chunks: list[dict],
                      result: ToolResult) -> tuple[list[dict], list[dict]]:
    """What one tool's result adds to the turn's citations and chunks.

    Returns both because a `ToolResult` carries both, and splitting it into two
    calls would make the caller re-derive which of them this result touched.
    """
    return (
        merge_citations(citations, result.citations),
        merge_chunks(chunks, result.retrieved_chunks),
    )


def initial_state(
        context: UserContext,
        messages: list,
        reference_notes: list[dict] | None = None) -> FinderState:
    return {
        "context": context,
        "messages": list(messages),
        "steps": 0,
        "tool_call": None,
        "citations": [],
        "retrieved_chunks": [],
        "reference_notes": list(reference_notes or []),
        "trace": {
            "tools": [],
            "routes": [],
        },
    }


def merge_reference_notes(existing: list[dict], current: list[dict]) -> list[dict]:
    merged = list(existing)

    for citation in current:
        merged = [item for item in merged
                  if item.get("note_id") != citation.get("note_id")]
        merged.append(citation)

    return merged[-20:]
