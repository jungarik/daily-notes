"""The agent roster, and the lookups the loop routes by.

Registration is where a conflicting farm is rejected: a duplicate agent name or a
tool name claimed by two agents raises at startup, not on the turn that happens
to hit it.
"""

from agents.contracts import AgentSpec

RESPONDER = "responder"
ROUTER = "router"

# Names an agent used to be registered under, mapped to what it is called now.
#
# A renamed agent is not only a code change: its old name is already written
# into `agent_states` rows and into the `pending` blob a suspended turn stored,
# so a user who was mid-confirmation when the deploy landed resumes through a
# name this farm no longer has. One entry here keeps that turn resumable; drop
# it once no pending row can still carry the old name.
LEGACY_NAMES = {"enrich": "enricher"}


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
        """The agent registered under this name, or the one it was renamed to.

        Resolving the rename here rather than at each call site is what keeps
        the rename invisible: the loop asks for whatever name the stored row
        carries and gets a live agent back.
        """
        agent = self._agents.get(name) or self._agents.get(LEGACY_NAMES.get(name))

        if agent is None:
            raise LookupError(f"Unknown agent: {name}")

        return agent

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
