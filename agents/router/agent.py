"""The router: who runs the next hop.

Named `agent.py` for the folder's shape, not because it is a peer in the farm —
it is the one `agent.py` with no `SPEC`, because it is what *chooses* the agents
the registry holds. The broker takes it as a constructor argument; it is never
registered and never takes a hop of its own.

The broker (`agents/runtime/broker.py`) drives a turn; this decides each hop.
Splitting them means each file has one reason to change: a new routing rule
lands here without touching the loop, and a change to how a hop is saved or
suspended never touches routing. This package is the only one that holds the
registry — the broker looks nothing up itself.

Three cases, cheapest first (`devdoc/agent-broker.md`):

  1. the turn is finishing — the responder takes the hop;
  2. an entry tool name resolves it — the previous model call already chose;
  3. otherwise ask the model, which sees the candidates, the user's message and
     the history of what has already run.

The responder is an ordinary hop, not a step outside the loop: it is picked here
like anyone else. The router will hand it back as often as it is asked — the
broker stops asking once a hop has produced a reply, which is what ends a turn.

Case 3 lives at the bottom of this file as `select_agent_name`, but reaches
`Router` as the injected `select_model` callable rather than by being called
directly. Same module, still a seam: routing stays testable with no model, and
a different selection strategy is a different callable rather than an edit to
the class. Without one the router falls straight through to the responder after
case 2.
"""

import json
import logging

import config
from agents.contracts import AgentSpec, HistoryEntry
from agents.router.prompts import SYSTEM, selection_request
from agents.runtime import model_gateway

logger = logging.getLogger(__name__)


class Router:
    """Picks the next agent for one hop, and is the only holder of the registry.

    The broker asks it who runs next and looks nothing up itself, so the roster
    has exactly one reader inside the farm.

    `always_ask_model` forces case 3 for every hop, skipping the entry-tool
    shortcut. It is on in dev and in the eval harness, so the path production
    almost never takes is the path a local turn always takes.
    """

    def __init__(self, registry, select_model=None, always_ask_model: bool = False):
        self._registry = registry
        self._select_model = select_model
        self._always_ask_model = always_ask_model

    def get_agent(self, name: str) -> AgentSpec:
        """The agent registered under a name.

        Raises on an unknown name: a suspended turn naming an agent that no
        longer exists is a deploy-time mistake, and a silent `None` would turn it
        into a confusing failure three frames later.
        """
        return self._registry.get(name)

    def select_agent(self, message: str, turns: tuple[HistoryEntry, ...],
                     entry_tool: str | None, force_responder: bool = False) -> AgentSpec | None:
        """The agent this hop belongs to, or None when the turn has run out of
        moves.

        `force_responder` says the turn is finishing — it is the caller's last
        slot, or a hop asked the user or failed. The router does not work that
        out itself: it never inspects a hop's status, only which agents have
        already run.

        When no work agent can be picked the responder takes the hop, so a turn
        ends with a reply rather than with silence. An entry tool nothing claims
        is not a dead end either: it falls through to the model, and then to the
        responder.
        """
        if force_responder:
            return self._registry.find_responder()

        addressed = (
            self._registry.find_by_entry_tool(entry_tool)
            if entry_tool is not None and not self._always_ask_model
            else None)

        if addressed is not None:
            return addressed

        candidates = self._candidates(turns)
        chosen = (
            self._select_model(candidates, message, turns)
            if candidates and self._select_model is not None
            else None)

        if chosen is None:
            return self._registry.find_responder()

        return self._registry.get(chosen)

    def _candidates(self, turns: tuple[HistoryEntry, ...]) -> list[dict]:
        """The agents that have not run yet.

        "One agent, one entry" is enforced by this list rather than by asking the
        prompt nicely — and because an empty list short-circuits, the common
        single-agent turn ends without a model call at all.
        """
        ran_agent = {turn.agent for turn in turns}

        return [agent for agent in self._registry.list_agents() if agent["name"] not in ran_agent]


# --- Case 3: asking a model which agent runs next ---------------------------
#
# Deliberately conservative. A model that answers with a name nobody registered,
# or with prose instead of JSON, ends the turn rather than routing somewhere
# arbitrary — the responder still gets its hop, so the user is answered either
# way. Routing badly is worse than routing nowhere.


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
