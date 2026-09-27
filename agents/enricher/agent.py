"""The enricher agent: note writes, end to end.

One module, because there is one job with two halves the loop calls in turn:
`start` plans the single write the user's message implies and pauses for
confirmation, `resume` performs it once approved.

Two things differ from `reminder/agent.py`, and both are the loop contract
earning its keep rather than bending:

  - the enricher owns five write tools whose results have five different shapes, so
    `_collect_refs` reads the note from the result when it is there and from the
    action's args when it is not;
  - `link_notes` is a *select* action: the user does not merely approve it, they
    choose which notes to link. That choice arrives in `decision["selection"]`,
    which is exactly what `resume(token, decision, context)` exists for.

What stays outside: the planning graph (`graph.py`), its prompt, its state, and
the tools (`tools/enricher/`). This agent owns no SQL.

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
    restore_clock,
)
from agents.enricher.graph import ACTION_PLAN_GRAPH
from agents.enricher.prompts import planning_messages
from agents.runtime.execute_tool import execute_allowed_tool, execute_tool
from tools import enricher as tools
from tools.enricher import TOOL_SPECS

logger = logging.getLogger(__name__)

NAME = "enricher"

# Written against the classifier's: this one changes what a note *is* — its
# text, one specific field, or what it connects to — while filing a note into
# the vault is the classifier's single pass. The router picks between the two
# on these sentences alone, so the last line is a boundary, not a flourish.
DESCRIPTION = (
    "Creates and edits notes: writing a new note, moving one note to a folder "
    "path, adding tags to a note, and linking notes to each other. Use when "
    "the request is about capturing note content or changing one specific "
    "thing about a note. Does not decide a note's full metadata in one pass "
    "(type, title, path, tags and priority together) and does not schedule "
    "anything.")

# Every prior hop is readable: an agent plans better knowing what the
# turn already found. The allowlist stays as the guard against a
# mistake — a copied adapter reaching for a state it never meant to —
# and what actually reaches a prompt is the fields this agent picks.
MAY_READ = ("*",)

# What a planner takes out of a peer's state: what the turn *found* (a finder's
# answer and the notes behind it) and what it *decided* (a peer's write, planned
# or performed). Without the second group a turn like "remind me about this and
# file it" plans the note blind to the reminder the peer just scheduled.
#
# `trace` is deliberately absent: it says which nodes ran, which helps a human
# read a turn back and would otherwise fill this agent's prompt with tool dumps.
USABLE_STATE_FIELDS = (
    "answer",
    "citations",
    "retrieved_chunks",
    "planned",
    "action",
    "result",
)


SELECT_ACTION = "link_notes"


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
            logger.warning("enricher could not read %s state on turn %s",
                           entry.agent, correlation_id)
            continue

        state = saved.data.get("state") or {}
        kept = {key: state[key] for key in USABLE_STATE_FIELDS if key in state}

        if kept:
            prior[entry.agent] = kept

    return prior


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
        "prior_states": _read_prior_states(
            request.context["user_id"], request.history, request.correlation_id),
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
        logger.exception("enricher planning failed for user %s", user_id)

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
    now, tz, locale = restore_clock(request.context)
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
    now, tz, locale = restore_clock(context)
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
    may_read=MAY_READ,
)
