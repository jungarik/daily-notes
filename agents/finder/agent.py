"""The finder's seat in the farm.

Adapts the read-and-answer vertical to the loop's `start` contract. It is the
agent that knows the vault: it searches, reads notes and neighbours, and
composes an answer.

Two things it deliberately does not do, both of which the farm now owns:

  - **it never writes, and never names who does.** The conversation controller
    it was copied from could call `perform_action` / `set_reminder` to hand a
    write off; finder has no such tools. The loop's router picks the agent
    that owns a write, so finder stays a peer that knows nothing about its
    peers.
  - **it never pauses.** With no approval interrupt, a hop runs start to finish,
    so there is no `resume` and no checkpoint of its own.

The answer goes into `AgentResult.state`, not into a reply: the responder is
the one agent that speaks to the user, and it is what turns this state into
prose.

Nothing in this module imports another agent.
"""

import logging
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import config
from agents.contracts import AgentRequest, AgentResult, AgentSpec, Ref, UserContext
from agents.finder.graph import FINDER_GRAPH
from agents.finder.prompts import with_system
from agents.finder.state import Ctx, initial_state
from agents.runtime import checkpoint

logger = logging.getLogger(__name__)

NAME = "finder"

DESCRIPTION = (
    "Answers questions about what the user has captured — searching their "
    "notes, reading one, following its links, listing reminders or an agenda. "
    "Use for anything the user wants to know or find. Reads only; it never "
    "creates, edits or schedules anything.")

def _restore_clock(context: UserContext) -> tuple:
    """The caller's clock and locale, restored from the envelope's plain JSON."""
    raw_now = context.get("now")
    now = datetime.fromisoformat(raw_now) if isinstance(raw_now, str) else raw_now
    raw_tz = context.get("tz")
    tz = ZoneInfo(raw_tz) if raw_tz else None

    return now, tz, context.get("locale") or "en"


def _build_messages(request: AgentRequest, now, tz) -> list[dict]:
    """The conversation so far, plus this turn's message.

    Prior turns arrive as a reference rather than as loop state: they belong
    to the calling section's thread, which the farm knows nothing about.
    """
    history = request.references.get("messages") or []

    return [
        *with_system(list(history), now, tz),
        {"role": "user", "content": request.message},
    ]


def _collect_refs(citations: list[dict]) -> tuple[Ref, ...]:
    """One typed ref per note the answer drew on.

    Reading is not producing, so these say which notes the turn touched rather
    than claiming anything was changed — enough for the responder to count, and
    for the turn tree to show what the answer rested on.
    """
    return tuple(
        Ref("note", str(citation["note_id"]))
        for citation in citations
        if citation.get("note_id") is not None)


def start(request: AgentRequest) -> AgentResult:
    """Answer the user's question from their own notes."""
    now, tz, locale = _restore_clock(request.context)
    ctx = Ctx(request.context["user_id"], now, tz=tz, locale=locale)
    graph_config = checkpoint.graph_config(NAME, uuid.uuid4(), config.AGENT_MAX_STEPS)
    state = FINDER_GRAPH.invoke(
        initial_state(ctx, _build_messages(request, now, tz),
                      request.references.get("reference_notes")),
        graph_config)
    citations = state.get("citations") or []

    return AgentResult(
        status="done",
        state={
            "answer": state.get("reply") or "",
            "citations": citations,
            "trace": state.get("trace") or {},
        },
        produced=_collect_refs(citations))


SPEC = AgentSpec(
    name=NAME,
    description=DESCRIPTION,
    start=start,
    entry_tools=(),
)
