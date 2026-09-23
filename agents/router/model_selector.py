"""Case 3: asking a model which agent runs next.

This is the `select_model` seam the router takes, built as a plain callable so
the router stays testable without a model and so a different selection strategy
is a different callable rather than an edit here.

It is deliberately conservative. A model that answers with a name nobody
registered, or with prose instead of JSON, ends the turn rather than routing
somewhere arbitrary — the responder still gets its hop, so the user is answered
either way. Routing badly is worse than routing nowhere.
"""

import json
import logging

import config
from agents.contracts import HistoryEntry
from agents.router.routing_prompts import SYSTEM, selection_request
from agents.runtime import model_gateway

logger = logging.getLogger(__name__)


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
            "content": selection_request(candidates, message, render_hops(history)),
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
    and the router's own fallback — the responder — still applies.
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
