"""The enrich agent: note writes, end to end.

One module, because there is one job with two halves the loop calls in turn:
`start` plans the single write the user's message implies and pauses for
confirmation, `resume` performs it once approved.

Two things differ from `reminder/agent.py`, and both are the loop contract
earning its keep rather than bending:

  - enrich owns five write tools whose results have five different shapes, so
    `_collect_refs` reads the note from the result when it is there and from the
    action's args when it is not;
  - `link_notes` is a *select* action: the user does not merely approve it, they
    choose which notes to link. That choice arrives in `decision["selection"]`,
    which is exactly what `resume(token, decision, context)` exists for.

What stays outside: the planning graph (`graph.py`), its prompt, its state, and
the tools (`tools/enrich/`). This agent owns no SQL.

Nothing in this module imports another agent.
"""

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from agents.contracts import (
    AgentRequest,
    AgentResult,
    AgentSpec,
    PlanRequest,
    Ref,
    ToolResult,
    UserContext,
)
from agents.enrich.graph import ACTION_PLAN_GRAPH
from agents.enrich.prompts import planning_messages
from agents.runtime.execute_tool import execute_tool
from tools import enrich as tools
from tools.enrich import TOOL_SPECS

logger = logging.getLogger(__name__)

NAME = "enrich"

DESCRIPTION = (
    "Creates and edits notes: writing a new note, changing a note's folder "
    "path, adding tags, filling in a note's metadata, and linking notes to each "
    "other. Use when the request is about capturing or reorganising note "
    "content. Does not schedule anything.")

SELECT_ACTION = "link_notes"


def _restore_clock(context: UserContext) -> tuple:
    """The caller's clock and locale, restored from the envelope's plain JSON."""
    raw_now = context.get("now")
    now = datetime.fromisoformat(raw_now) if isinstance(raw_now, str) else raw_now
    raw_tz = context.get("tz")
    tz = ZoneInfo(raw_tz) if isinstance(raw_tz, str) and raw_tz else None

    return now, tz, context.get("locale") or "en"


def _build_tool_context(user_id: int, now, tz, locale: str) -> dict:
    """The clock every tool call on this turn is scoped by, as plain JSON."""
    return {
        "user_id": user_id,
        "now": now.isoformat() if hasattr(now, "isoformat") else now,
        "tz": str(tz) if tz is not None else None,
        "locale": locale,
    }


def _read_note_ids(references: dict) -> list[int]:
    """The note ids the turn referenced, as ints.

    They arrive from a client through the loop, so an unparseable one is
    dropped rather than raising — losing one reference is better than losing the
    write.
    """
    note_ids = []

    for note_id in references.get("referenced_note_ids") or []:
        try:
            note_ids.append(int(note_id))
        except (TypeError, ValueError):
            continue

    return note_ids


def _build_plan_request(request: AgentRequest, now, tz, locale: str) -> PlanRequest:
    """The planning contract, from the envelope the loop handed over.

    The material the caller had already resolved arrives in `references`; the
    clock and locale arrive in `context`.
    """
    references = request.references

    return {
        "instruction": request.message.strip(),
        "conversation_summary": str(references.get("conversation_summary") or ""),
        "referenced_note_ids": _read_note_ids(references),
        "citations": list(references.get("citations") or []),
        "resolved_entities": dict(references.get("resolved_entities") or {}),
        "locale": locale,
        "timezone": str(tz) if tz is not None else None,
        "now": now.isoformat() if hasattr(now, "isoformat") else None,
    }


def _plan_action(user_id: int, plan_request: PlanRequest, tool_context: dict) -> dict | None:
    """Decide the single write an instruction implies, executing nothing.

    Returns `{name, args, summary}` for a write tool, or None when nothing
    concrete could be determined — an ordinary outcome, not a failure. A graph
    that raises is also None: the turn then finishes without a write rather than
    failing, and the responder says so.
    """
    try:
        result = ACTION_PLAN_GRAPH.invoke({
            "messages": planning_messages(plan_request),
            "user_context": tool_context,
            "tool_specs": TOOL_SPECS,
            "steps": 0,
            "tool_call": None,
            "action": None,
        })

        return result.get("action")
    except Exception:
        logger.exception("enrich planning failed for user %s", user_id)

        return None


def _chosen_note_ids(selection) -> list[int]:
    """The note ids the user ticked, de-duplicated and in the order they came.

    Anything unparseable is dropped rather than raising: the selection arrives
    from a client, and one bad id should not lose the rest of the choice.
    """
    chosen = []

    for value in selection or []:
        try:
            note_id = int(value)
        except (TypeError, ValueError):
            continue

        if note_id not in chosen:
            chosen.append(note_id)

    return chosen


def _with_selection(action: dict, decision: dict) -> dict:
    """The action as the user confirmed it.

    Only `link_notes` is a choice rather than a yes/no, so only it is rewritten.
    Returns a new action — the token's copy is never mutated.
    """
    selection = decision.get("selection")

    if selection is None or action.get("name") != SELECT_ACTION:
        return action

    return {
        **action,
        "args": {
            **(action.get("args") or {}),
            "linked_note_ids": _chosen_note_ids(selection),
        },
    }


def _collect_refs(action: dict, data: dict) -> tuple[Ref, ...]:
    """What the write made or changed, as the history sees it.

    The five write tools report differently — `create_note` returns a fresh
    `note_id`, `set_note_path` returns only `{ok, path}` — so the note is taken
    from the result when it is there and from the action's args when it is not.
    A tag or a path is not an entity with an id, so those add no ref beyond the
    note they changed.
    """
    note_id = data.get("note_id") or (action.get("args") or {}).get("note_id")
    made = [] if note_id is None else [Ref(kind="note", id=str(note_id))]

    for target_id in data.get("linked_note_ids") or []:
        made.append(Ref(kind="link", id=f"{note_id}-{target_id}"))

    return tuple(made)


def start(request: AgentRequest) -> AgentResult:
    """Plan the write the message implies and pause for confirmation."""
    user_id = request.context["user_id"]
    now, tz, locale = _restore_clock(request.context)
    action = _plan_action(
        user_id,
        _build_plan_request(request, now, tz, locale),
        _build_tool_context(user_id, now, tz, locale))

    if action is None:
        return AgentResult(
            status="done",
            state={"planned": None, "message": request.message})

    return AgentResult(
        status="needs_input",
        state={"planned": action, "message": request.message},
        ask={
            "kind": "select" if action.get("name") == SELECT_ACTION else "confirm",
            "action": action,
            "summary": action.get("summary"),
        },
        token=json.dumps(action, default=str))


def resume(token: str, decision: dict, context: UserContext) -> AgentResult:
    """Perform the approved write and report what it made.

    The loop calls this only on approval and only once per action, so there is
    no decline branch and no idempotency check here.
    """
    action = _with_selection(json.loads(token), decision)
    now, tz, locale = _restore_clock(context)
    result = execute_tool(
        tools.TOOLS,
        _build_tool_context(context["user_id"], now, tz, locale),
        action["name"],
        action.get("args") or {},
        NAME)

    # `execute_tool` degrades to a plain string when the tool is unknown or
    # raised, so anything that is not a ToolResult is a failure, not a quiet
    # success with nothing to report.
    if not isinstance(result, ToolResult):
        return AgentResult(status="failed", state={"action": action}, error=str(result))

    data = result.data or {}

    if data.get("error"):
        return AgentResult(status="failed", state={"action": action}, error=data["error"])

    return AgentResult(
        status="done",
        state={"action": action, "result": data},
        produced=_collect_refs(action, data))



SPEC = AgentSpec(
    name=NAME,
    description=DESCRIPTION,
    start=start,
    resume=resume,
    entry_tools=("perform_action",),
)
