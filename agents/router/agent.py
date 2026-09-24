"""The router agent: which agent takes the next hop.

A registered peer like any other — a `SPEC`, a `start(request) -> AgentResult`,
and a hop of its own in the turn history. What makes it unusual is only that
the loop reaches it by name rather than by routing to it: something has to
choose first, and that something cannot itself be chosen.

**It runs only when a choice needs a model.** The loop resolves the two free
cases itself — the responder when the turn is finishing, and an `entry_agent`
when the caller named one — because both are loop-local state (`hops_left`, the
unspent entry agent) rather than routing policy. So a
turn that never needs a model has no router hop and no router row, which is the
honest record: the router appears exactly where a model made a decision.

**It answers in `produced`.** `Ref("agent", "<name>")` names the agent that
runs next; an empty `produced` means it declined, and the loop falls through to
the responder. This is the one place the farm reserves a `Ref.kind` — see
`agents/contracts/ref.py`.

It is conservative by construction. A model that answers with a name nobody
registered, or with prose instead of JSON, declines rather than routing
somewhere arbitrary. The responder still gets its hop, so the user is answered
either way: routing badly is worse than routing nowhere.

Nothing in this module imports another agent.
"""

import json
import logging

import config
from agents.contracts import AgentRequest, AgentResult, AgentSpec, HistoryEntry, Ref
from agents.router.prompts import SYSTEM, selection_prompt
from agents.runtime import model_gateway

logger = logging.getLogger(__name__)

NAME = "router"

DESCRIPTION = (
    "Picks the agent that takes the next hop. Never a candidate for its own "
    "choice, and never routed to — the loop reaches it by name.")

# The kind the loop reads off this agent's `produced` to learn its decision.
AGENT_KIND = "agent"


def start(request: AgentRequest) -> AgentResult:
    """Choose the agent for this hop from the candidates the loop resolved.

    The candidates arrive in `references` because the roster is the registry's
    and this agent holds no handle on it — the loop, which does, passes it in.
    It is the whole roster every hop, including agents that already ran: a turn
    often needs the same one twice, and what has happened reaches this agent as
    history, to inform the choice rather than to narrow it.

    Never fails: a model that is down must not take the turn with it. A decline
    is `done` with nothing produced, and the loop reads that as "nothing left
    to do".
    """
    candidates = list(request.references.get("candidates") or [])

    if not candidates:
        return AgentResult(status="done", state={"candidates": [], "chosen": None})

    chosen = select_agent_name(candidates, request.message, request.history)
    produced = () if chosen is None else (Ref(kind=AGENT_KIND, id=chosen),)

    return AgentResult(
        status="done",
        state={
            "candidates": [candidate["name"] for candidate in candidates],
            "chosen": chosen,
        },
        produced=produced)


def render_hops(history: tuple[HistoryEntry, ...]) -> list[dict]:
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


def build_request(candidates: list[dict], message: str, history) -> dict:
    return {
        "model": config.ROUTER_MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{
            "role": "system",
            "content": SYSTEM,
        }, {
            "role": "user",
            "content": selection_prompt(candidates, message, render_hops(history)),
        }],
    }


def choose_name(answer: str, candidates: list[dict]) -> str | None:
    """The chosen agent's name, or None when the model declined or misbehaved.

    Every failure mode collapses to None: unparseable JSON, a missing key, a
    name that is not on the candidate list. The caller treats None as "nothing
    left to do", which is the safe reading of a router that cannot be trusted.
    """
    try:
        chosen = json.loads(answer).get("agent")
    except (TypeError, ValueError, AttributeError):
        logger.warning("router model returned unparseable JSON: %.200s", answer)

        return None

    if chosen is None:
        return None

    if chosen not in {candidate["name"] for candidate in candidates}:
        logger.warning("router model chose an agent that was not offered: %r", chosen)

        return None

    return chosen


def select_agent_name(candidates: list[dict], message: str, history) -> str | None:
    """Ask the model which of these agents should take the next hop.

    Never raises: a model that is down or slow must not take the turn with it,
    and the loop's own fallback — the responder — still applies.
    """
    try:
        model_response = model_gateway.chat_completion(
            **build_request(candidates, message, history))
        # Reading the response is inside the guard too: a completion with no
        # choices raises on subscript, and that is a model misbehaving just as
        # much as a timeout is.
        answer = model_response.choices[0].message.content or ""
    except Exception as exc:
        logger.warning("router model call failed, ending the turn: %s", exc)

        return None

    return choose_name(answer, candidates)


SPEC = AgentSpec(
    name=NAME,
    description=DESCRIPTION,
    start=start,
)
