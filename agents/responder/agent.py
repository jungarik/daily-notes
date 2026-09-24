"""The responder: the one agent that writes to the user.

It is an ordinary hop the router picks last, on every turn — finished, failed,
or waiting on a confirmation — and it produces nothing but prose. Keeping the
reply here is what stops voice and localisation from being reinvented in each
work agent, and it is why those agents' `produced` can be refs rather than
sentences.

Two properties this module owes the farm:

  - **it never fails.** The model call is wrapped, and a deterministic template
    over the turn history is the fallback. A turn that saved a note must not
    lose that fact because a reply could not be phrased.
  - **it reports what happened, not what it hopes.** The prompt is rendered from
    the history's statuses and typed refs, so there is no agent-written prose in
    it for the model to launder into a claim.

Nothing in this module imports another agent.
"""

import logging

import config
from agents.contracts import (
    AgentRequest,
    AgentResult,
    AgentSpec,
    HistoryEntry,
    ToolResult,
)
from agents.responder.prompts import SYSTEM, reply_request
from agents.runtime import model_gateway
from agents.runtime.execute_tool import execute_allowed_tool
from tools import responder as tools

logger = logging.getLogger(__name__)

NAME = "responder"

DESCRIPTION = (
    "Writes the user-facing reply. Not a work agent — the router picks it when "
    "the turn is finishing, and never as a candidate.")

# It relays what every other agent did, so it reads every agent's state.
MAY_READ = ("*",)

NOTHING_HAPPENED = "I could not do anything with that."


def _render_hops(history: tuple[HistoryEntry, ...]) -> list[dict]:
    """The turn history as plain JSON for the prompt."""
    return [
        {
            "agent": entry.agent,
            "status": entry.status,
            "produced": [{"kind": ref.kind, "id": ref.id} for ref in entry.produced],
            "error": entry.error,
        }
        for entry in history
    ]


def _describe(entry: HistoryEntry) -> str:
    """One hop, in the terse register the fallback uses."""
    if entry.status == "failed":
        return f"{entry.agent} failed"

    counts: dict[str, int] = {}

    for ref in entry.produced:
        counts[ref.kind] = counts.get(ref.kind, 0) + 1

    if not counts:
        return f"{entry.agent} had nothing to do"

    made = ", ".join(
        f"{total} {kind}" if total == 1 else f"{total} {kind}s"
        for kind, total in counts.items())

    return f"{entry.agent} saved {made}"


def write_fallback(history: tuple[HistoryEntry, ...]) -> str:
    """A reply built from the history alone, with no model and no way to fail.

    Terse, never wrong. The user is never left unsure whether their note was
    saved because a model call did not come back.
    """
    described = [_describe(entry) for entry in history if entry.agent != NAME]

    return "; ".join(described).capitalize() + "." if described else NOTHING_HAPPENED


def _read_states(request: AgentRequest) -> dict[str, dict]:
    """What each earlier hop actually did, keyed by agent.

    The history carries refs, not prose, so an answer another agent composed —
    the point of a Q&A turn — is only reachable through `read_state`. Read
    deterministically before the one model call rather than as a tool the model
    may call: the reply path runs on every turn and does not need a second
    round-trip to decide it wants the record it is about to report on.

    A state that cannot be read is skipped, never fatal: a thinner prompt is a
    worse reply, and a missing reply is a worse turn.
    """
    context = {
        "user_id": request.context["user_id"],
        "agent": request.agent,
        "may_read": MAY_READ,
    }
    states = {}

    for entry in request.history:
        if entry.state_id is None or entry.agent == NAME:
            continue

        saved = execute_allowed_tool(
            tools.TOOLS,
            tools.CONTEXT_TOOLS,
            context,
            "read_state",
            {"state_id": entry.state_id},
            NAME)

        if isinstance(saved, ToolResult) and not (saved.data or {}).get("error"):
            states[entry.agent] = saved.data.get("state") or {}
        else:
            logger.warning("responder could not read %s state on turn %s",
                           entry.agent, request.correlation_id)

    return states


def _build_request(request: AgentRequest, awaiting: str | None) -> dict:
    return {
        "model": config.RESPONDER_MODEL,
        "temperature": 0.2,
        "messages": [{
            "role": "system",
            "content": SYSTEM,
        }, {
            "role": "user",
            "content": reply_request(
                request.message,
                _render_hops(request.history),
                request.context.get("locale") or "en",
                awaiting,
                _read_states(request)),
        }],
    }


def _find_awaiting(history: tuple[HistoryEntry, ...]) -> str | None:
    """Which agent is waiting on the user, if the turn is suspending.

    Read from the history rather than handed over by the loop: the responder
    is an ordinary hop and gets no channel the other agents do not have.
    """
    for entry in history:
        if entry.status == "needs_input":
            return entry.agent

    return None


def start(request: AgentRequest) -> AgentResult:
    """Write the turn's reply.

    The same agent phrases "here is what I am about to do" and "here is what I
    did" — which of the two is decided by the history, not a second entry point.
    """
    awaiting = _find_awaiting(request.history)
    fallback = write_fallback(request.history)

    try:
        model_response = model_gateway.chat_completion(**_build_request(request, awaiting))
        reply = (model_response.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.warning("responder fell back to the template on turn %s: %s",
                       request.correlation_id, exc)

        return AgentResult(
            status="done",
            state={"reply": fallback, "fallback": True, "error": str(exc)},
            reply=fallback)

    # An empty completion is a failure the SDK does not raise on; the template
    # is better than handing the user a blank reply.
    return AgentResult(
        status="done",
        state={"reply": reply or fallback, "fallback": not reply},
        reply=reply or fallback)


SPEC = AgentSpec(
    name=NAME,
    description=DESCRIPTION,
    start=start,
    may_read=("*",),
)
