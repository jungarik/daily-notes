"""The reminder agent: scheduling, end to end.

One module, because there is one job with two halves the loop calls in turn:
`start` plans the write the user's message implies and pauses for confirmation,
`resume` performs it once approved. Everything below them serves those two —
hydrating the notes an instruction points at, shaping the planning request,
reading what the write made.

What stays outside: the planning graph (`graph.py`), its prompt, its state, and
the tools (`tools/reminder/`). This agent owns no SQL.

The resume token is this agent's own business: here it is the planned action,
because that is all it needs to finish. The loop never opens it.

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
    HistoryEntry,
    PlanRequest,
    Ref,
    ToolResult,
    UserContext,
    build_context,
    restore_clock,
)
from agents.reminder.graph import PLAN_GRAPH
from agents.runtime.execute_tool import execute_allowed_tool, execute_tool
from tools import reminder as tools

logger = logging.getLogger(__name__)

NAME = "reminder"

DESCRIPTION = (
    "Schedules a reminder for a time the user described in words. Use when the "
    "request is about being reminded, alerted, or nudged at some point in the "
    "future. Does not create or edit note content.")

# Every prior hop is readable: an agent plans better knowing what the
# turn already found. The allowlist stays as the guard against a
# mistake — a copied adapter reaching for a state it never meant to —
# and what actually reaches a prompt is the fields this agent picks.
MAY_READ = ("*",)

# What a planner takes out of a peer's state. `trace` is deliberately absent:
# it says which nodes ran, which helps a human read a turn back and would
# otherwise fill this agent's prompt with tool dumps.
USABLE_STATE_FIELDS = ("answer", "citations", "retrieved_chunks")



def _read_note_ids(references: dict) -> list[int]:
    """The note ids the turn referenced, as ints.

    They arrive from a client through the loop, so an unparseable one is
    dropped rather than raising — losing one reference is better than losing the
    reminder.
    """
    note_ids = []

    for note_id in references.get("referenced_note_ids") or []:
        try:
            note_ids.append(int(note_id))
        except (TypeError, ValueError):
            continue

    return note_ids


def _read_prior_states(user_id: int,
                       history: tuple[HistoryEntry, ...],
                       correlation_id: str) -> dict[str, dict]:
    """What earlier hops in this turn produced, keyed by agent.

    The history carries typed refs, not prose, so what another agent actually
    found is only reachable through `read_state`. Read deterministically before
    planning rather than as a tool the planner may call: the planner has a small
    step budget and should spend it on resolving the write, not on deciding it
    wants a record already sitting in the turn.

    Only the fields a planner can use are kept. `trace` records which nodes ran
    — useful for reading a turn back, not for planning — and taking it would put
    the whole debug blob in the prompt.

    A state that cannot be read is skipped, never fatal: planning with less
    context is worse than planning with more, and far better than no plan.
    """
    context = {
        "user_id": user_id,
        "agent": NAME,
        "may_read": MAY_READ,
    }
    prior = {}

    for entry in history:
        if entry.state_id is None or entry.agent == NAME:
            continue

        saved = execute_allowed_tool(
            tools.TOOLS,
            tools.CONTEXT_TOOLS,
            context,
            "read_state",
            {"state_id": entry.state_id},
            NAME)

        if not isinstance(saved, ToolResult) or (saved.data or {}).get("error"):
            logger.warning("reminder could not read %s state on turn %s",
                           entry.agent, correlation_id)
            continue

        state = saved.data.get("state") or {}
        kept = {key: state[key] for key in USABLE_STATE_FIELDS if key in state}

        if kept:
            prior[entry.agent] = kept

    return prior


def _cited_note_ids(prior_states: dict[str, dict]) -> list[int]:
    """The notes earlier hops cited, in the order they were found.

    A reminder needs a note to hang on. When the client named one it is in
    `references`; when the user said "remind me about that" after a search, the
    only record of which note "that" is lives in the finder's citations.
    """
    note_ids = []

    for state in prior_states.values():
        for citation in state.get("citations") or []:
            try:
                note_id = int(citation["note_id"])
            except (KeyError, TypeError, ValueError):
                continue

            if note_id not in note_ids:
                note_ids.append(note_id)

    return note_ids


def _build_plan_request(request: AgentRequest, now, tz, locale: str) -> PlanRequest:
    """The planning contract, from the envelope the loop handed over.

    The material the caller had already resolved arrives in `references`; the
    clock and locale arrive in `context`; what earlier hops in this turn found
    is read from their saved state.
    """
    references = request.references
    prior_states = _read_prior_states(
        request.context["user_id"], request.history, request.correlation_id)

    return {
        "instruction": request.message.strip(),
        "conversation_summary": str(references.get("conversation_summary") or ""),
        # What the client named wins; what an earlier hop found is the
        # fallback, so "remind me about that" after a search resolves.
        "referenced_note_ids": _read_note_ids(references) or _cited_note_ids(prior_states),
        "citations": list(references.get("citations") or []),
        "resolved_entities": dict(references.get("resolved_entities") or {}),
        "prior_states": prior_states,
        "locale": locale,
        "timezone": str(tz) if tz is not None else None,
        "now": now.isoformat() if hasattr(now, "isoformat") else None,
    }


def _read_note(result, note_id: int) -> dict | None:
    """The note a context tool returned, keyed as the planner expects it, or
    None when the tool could not read it."""
    if not isinstance(result, ToolResult):
        return None

    note = result.data or {}

    if note.get("error"):
        return None

    return {**note, "note_id": note.get("id", note_id)}


def _read_referenced_notes(context: dict, note_ids: list[int]) -> list[dict]:
    """Hydrate the notes an instruction points at, one context tool call each.

    This is what lets the planner resolve "that note" — without it the
    instruction is an isolated sentence.
    """
    notes = []

    for note_id in note_ids:
        note = _read_note(
            execute_allowed_tool(
                tools.TOOLS,
                tools.CONTEXT_TOOLS,
                context,
                "get_note_context",
                {"note_id": note_id},
                NAME,
            ),
            note_id,
        )

        if note is not None:
            notes.append(note)

    return notes


def _collect_refs(data: dict) -> tuple[Ref, ...]:
    """What the write made, as the history sees it. Only ids the tool confirmed."""
    made = []

    for kind, key in (("reminder", "reminder_id"), ("note", "note_id")):
        value = data.get(key)

        if value is not None:
            made.append(Ref(kind=kind, id=str(value)))

    return tuple(made)


def _plan_action(user_id: int, plan_request: PlanRequest, now, locale: str) -> dict | None:
    """Resolve the reminder an instruction implies.

    Returns `{name, args, summary}`, or None when no time could be resolved —
    which is an ordinary outcome ("remind me about this sometime"), not a
    failure. A graph that raises is also None: the turn then finishes without a
    write rather than failing, and the responder says so.
    """
    try:
        result = PLAN_GRAPH.invoke({
            "contract": plan_request,
            "now": now,
            "locale": locale,
            "action": None,
            "events": [],
        })
    except Exception:
        logger.exception("reminder planning failed for user %s", user_id)

        return None

    if result["action"] is None:
        logger.info("no reminder planned for user %s: %s", user_id, result["events"])

    return result["action"]


def start(request: AgentRequest) -> AgentResult:
    """Plan the reminder the message implies and pause for confirmation."""
    user_id = request.context["user_id"]
    now, tz, locale = restore_clock(request.context)
    plan_request = _build_plan_request(request, now, tz, locale)
    plan_request["resolved_entities"]["referenced_notes"] = _read_referenced_notes(
        build_context(user_id, now, tz=tz, locale=locale),
        plan_request["referenced_note_ids"])
    action = _plan_action(user_id, plan_request, now, locale)

    if action is None:
        return AgentResult(
            status="done",
            state={"planned": None, "message": request.message})

    return AgentResult(
        status="needs_input",
        state={"planned": action, "message": request.message},
        ask={"kind": "confirm", "action": action, "summary": action.get("summary")},
        token=json.dumps(action, default=str))


def resume(token: str, decision: dict, context: UserContext) -> AgentResult:
    """Perform the approved write and report what it made.

    The loop calls this only on approval and only once per action, so there is
    no decline branch and no idempotency check here.
    """
    action = json.loads(token)
    now, tz, locale = restore_clock(context)
    result = execute_tool(
        tools.TOOLS,
        build_context(context["user_id"], now, tz=tz, locale=locale),
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
        produced=_collect_refs(data))


SPEC = AgentSpec(
    name=NAME,
    description=DESCRIPTION,
    start=start,
    resume=resume,
    may_read=MAY_READ,
)
