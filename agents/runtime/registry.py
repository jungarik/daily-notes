"""The agent roster, and the lookups the loop routes by.

Registration is where a conflicting farm is rejected: a duplicate agent name or a
tool name claimed by two agents raises at startup, not on the turn that happens
to hit it.
"""

from agents.contracts import AgentSpec

RESPONDER = "responder"
ROUTER = "router"


class AgentRegistry:
    """Every agent in the farm, indexed by name and by entry tool."""

    def __init__(self):
        self._agents: dict[str, AgentSpec] = {}
        self._entry_tools: dict[str, str] = {}

    def register(self, agent: AgentSpec) -> None:
        if agent.name in self._agents:
            raise ValueError(f"Agent already registered: {agent.name}")

        for tool_name in agent.entry_tools:
            owner = self._entry_tools.get(tool_name)

            if owner is not None:
                raise ValueError(
                    f"Entry tool {tool_name!r} is claimed by {owner!r} and {agent.name!r}")

            self._entry_tools[tool_name] = agent.name

        self._agents[agent.name] = agent

    def get(self, name: str) -> AgentSpec:
        try:
            return self._agents[name]
        except KeyError as exc:
            raise LookupError(f"Unknown agent: {name}") from exc

    def find_by_entry_tool(self, tool_name: str) -> AgentSpec | None:
        """The agent a tool name addresses, or None when nothing claims it."""
        owner = self._entry_tools.get(tool_name)

        return None if owner is None else self._agents[owner]

    def find_responder(self) -> AgentSpec | None:
        """The reply-only agent."""
        return self._agents.get(RESPONDER)

    def find_router(self) -> AgentSpec | None:
        """The agent that chooses the next hop.

        Reached by name rather than by routing: something has to choose
        first, and that something cannot itself be chosen.
        """
        return self._agents.get(ROUTER)

    def list_agents(self) -> list[dict]:
        """What the router is shown: who exists and what they do.

        Both singletons are left out. The responder is not a choice — it
        takes the last hop by construction. The router is not a choice
        either, and offering it would let a decision pick itself.
        """
        return [
            {"name": agent.name, "description": agent.description}
            for agent in self._agents.values()
            if agent.name not in (RESPONDER, ROUTER)
        ]

    def may_read(self, reader: str, subject: str) -> bool:
        """Whether `reader`'s read_state tool may fetch a state `subject` wrote."""
        allowed = self.get(reader).may_read

        return "*" in allowed or subject in allowed
