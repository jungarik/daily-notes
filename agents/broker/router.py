"""Who runs next — the farm's routing policy, and nothing else.

The broker drives a turn; this decides each hop. Splitting them means each file
has one reason to change: a new routing rule lands here without touching the
loop, and a change to how a hop is saved or suspended never touches routing.

Three cases, cheapest first (`devdoc/agent-broker.md`):

  1. the responder hop is unconditional — it is not chosen here at all;
  2. an entry tool name resolves it — the previous model call already chose;
  3. otherwise ask the model, which sees the candidates, the user's message and
     the history of what has already run.

`select_model` is the case-3 seam and is optional: without one the router simply
runs out of moves after case 2, which is the farm's behaviour until the responder
lands in Phase 4.
"""

import logging

from agents.broker.contracts import AgentSpec, HistoryEntry

logger = logging.getLogger(__name__)


class Router:
    """Picks the next agent for one hop, and is the only holder of the registry.

    The broker asks it who runs next and looks nothing up itself, so the roster
    has exactly one reader inside the farm. (The composition root keeps its own
    reference — it built the registry and hands it to whatever else needs it,
    such as the Phase 3 `read_state` tool and its `may_read` allowlist. That is
    not routing, so it does not come through here.)

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

    def select_agent(self, message: str, turn_history: tuple[HistoryEntry, ...],
                     entry_tool: str | None) -> AgentSpec | None:
        """The agent this hop belongs to, or None when the turn has run out of
        moves."""
        if entry_tool is not None and not self._always_ask_model:
            return self._registry.find_by_entry_tool(entry_tool)

        if self._select_model is None:
            return None

        candidates = self._candidates(turn_history)

        if not candidates:
            return None

        chosen = self._select_model(candidates, message, turn_history)

        return None if chosen is None else self._registry.get(chosen)

    def _candidates(self, turn_history: tuple[HistoryEntry, ...]) -> list[dict]:
        """The agents that have not run yet.

        "One agent, one entry" is enforced by this list rather than by asking the
        prompt nicely — and because an empty list short-circuits, the common
        single-agent turn ends without a model call at all.
        """
        ran = {item.agent for item in turn_history}

        return [item for item in self._registry.list_agents() if item["name"] not in ran]
