"""The classifier agent: filing one note, end to end.

One module, because there is one job with two halves the loop calls in turn:
`start` classifies the note the turn points at and pauses for confirmation,
`resume` writes the metadata once approved. Everything below them serves those
two — resolving which note is meant, running the pipeline, shaping the ask.

What stays outside: the graph (`graph.py`), its prompt, its state, and the
tools (`tools/classifier/`). This agent owns no SQL.

The resume token is this agent's own business: here it is the planned action,
because that is all it needs to finish. The loop never opens it.

Nothing in this module imports another agent.
"""

import json
import logging

import i18n
from agents.classifier.graph import CLASSIFY_GRAPH
from agents.classifier.state import ClassifyState
from agents.contracts import (
    AgentRequest,
    AgentResult,
    AgentSpec,
    HistoryEntry,
    Ref,
    ToolResult,
    UserContext,
    build_context,
    restore_clock,
)
from agents.runtime.execute_tool import execute_allowed_tool, execute_tool
from tools import classifier as tools

logger = logging.getLogger(__name__)

NAME = "classifier"

# The router chooses between this and the enricher on wording alone, so the two
# descriptions are written against each other: this one files a note that
# already exists, the enricher changes what a note says or what it links to.
# "Does not create note text" is the line that keeps a capture from landing
# here, and it is load-bearing rather than decorative.
DESCRIPTION = (
    "Files an existing note into the vault: decides its type, title, folder "
    "path, tags and priority in one pass, using the user's existing folders and "
    "tags so the filing stays consistent. Use when the request is to classify, "
    "file, organise, tidy, categorise or 'sort out' a note, or to give it a "
    "proper title or folder. Does not create a note, edit its text, link it to "
    "other notes, or schedule anything.")

MAY_READ = ("*",)

# What this agent takes out of a peer's state: what the turn found, and what it
# decided. The second group is how "save this and file it properly" resolves —
# the note to file is the one the enricher's write just created.
USABLE_STATE_FIELDS = (
    "answer",
    "citations",
    "retrieved_chunks",
    "planned",
    "action",
    "result",
)

ACTION = "enrich_note"


def _read_note_ids(references: dict) -> list[int]:
    """The note ids the turn referenced, as ints.

    They arrive from a client through the loop, so an unparseable one is
    dropped rather than raising — losing one reference is better than losing
    the filing.
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
    did is only reachable through `read_state`. Read deterministically before
    the pipeline runs rather than as a tool a model may call: this agent makes
    one model call, inside `propose`, and it is about metadata rather than
    about which note to work on.

    A state that cannot be read is skipped, never fatal: filing with less
    context is worse than filing with more, and far better than not filing.
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
            logger.warning("classifier could not read %s state on turn %s",
                           entry.agent, correlation_id)
            continue

        state = saved.data.get("state") or {}
        kept = {key: state[key] for key in USABLE_STATE_FIELDS if key in state}

        if kept:
            prior[entry.agent] = kept

    return prior


def _find_known_note_ids(prior_states: dict[str, dict]) -> list[int]:
    """The notes earlier hops put on the table, best antecedent first.

    A filing needs a note to file. When the client named one it is in
    `references`; when the user said "and file it properly", the only record of
    which note "it" means is what the turn already did — a note a peer just
    wrote, or one the finder cited.

    A write is offered before a citation deliberately: after "save this and
    file it", "it" is the note that was just created, not one a search
    happened to surface along the way.
    """
    candidates = []

    for state in prior_states.values():
        written = state.get("result")

        if isinstance(written, dict):
            candidates.append(written.get("note_id"))

    for state in prior_states.values():
        for citation in state.get("citations") or []:
            if isinstance(citation, dict):
                candidates.append(citation.get("note_id"))

    note_ids = []

    for candidate in candidates:
        try:
            note_id = int(candidate)
        except (TypeError, ValueError):
            continue

        if note_id not in note_ids:
            note_ids.append(note_id)

    return note_ids


def _find_target(request: AgentRequest) -> int | None:
    """The note this turn wants filed, or None when nothing names one.

    What the client named wins; what an earlier hop wrote or found is the
    fallback. Only the first is used — filing is per-note, and guessing a
    second target from a list would file a note the user never mentioned.
    """
    named = _read_note_ids(request.references)

    if named:
        return named[0]

    known = _find_known_note_ids(_read_prior_states(
        request.context["user_id"], request.history, request.correlation_id))

    return known[0] if known else None


def _build_action(note_id: int, metadata: dict, locale: str) -> dict:
    """The write this filing proposes, with the summary the user confirms.

    `args` carries the metadata itself, not just the note id: the tool refuses
    a proposal that arrives without approved values, so what the user sees in
    the summary is exactly what `resume` will write.
    """
    return {
        "name": ACTION,
        "args": {"note_id": note_id, **metadata},
        "summary": i18n.t(
            locale,
            "action_enrich_note",
            title=metadata.get("title"),
            type=metadata.get("type"),
            path=metadata.get("path"),
            tags=", ".join(metadata.get("tags") or []),
            id=note_id),
    }


def _classify(user_id: int, note_id: int, context: UserContext) -> ClassifyState | None:
    """Run the pipeline over one note.

    Returns the final state, or None when the graph raised — which ends the
    turn without a filing rather than failing it, and the responder says so.
    A graph that merely could not read the note returns state carrying `error`,
    which is an ordinary outcome and not this branch.
    """
    try:
        return CLASSIFY_GRAPH.invoke({
            "user_context": context,
            "note_id": note_id,
            "text": "",
            "trace": [],
        })
    except Exception:
        logger.exception("classification failed for user %s note %s", user_id, note_id)

        return None


def start(request: AgentRequest) -> AgentResult:
    """Classify the note the turn points at and pause for confirmation."""
    user_id = request.context["user_id"]
    locale = request.context.get("locale") or "en"
    note_id = _find_target(request)

    if note_id is None:
        logger.info("no note to classify on turn %s", request.correlation_id)

        return AgentResult(
            status="done",
            state={"planned": None, "message": request.message})

    state = _classify(user_id, note_id, request.context)
    metadata = (state or {}).get("metadata")

    if not metadata:
        return AgentResult(
            status="done",
            state={
                "planned": None,
                "note_id": note_id,
                "message": request.message,
                "error": (state or {}).get("error"),
            })

    action = _build_action(note_id, metadata, locale)

    return AgentResult(
        status="needs_input",
        state={"planned": action, "note_id": note_id, "message": request.message},
        ask={"kind": "confirm", "action": action, "summary": action["summary"]},
        token=json.dumps(action, default=str))


def resume(token: str, decision: dict, context: UserContext) -> AgentResult:
    """Write the approved metadata and report what it changed.

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

    note_id = (action.get("args") or {}).get("note_id")

    return AgentResult(
        status="done",
        state={"action": action, "result": {**data, "note_id": note_id}},
        produced=() if note_id is None else (Ref(kind="note", id=str(note_id)),))


SPEC = AgentSpec(
    name=NAME,
    description=DESCRIPTION,
    start=start,
    resume=resume,
    may_read=MAY_READ,
)
