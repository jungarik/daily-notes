"""Guard the farm's shape: four peer agents, one composition root, no back doors.

The structure is the product here — a new capability is meant to be a file plus
a registry entry — so these assertions are about layout and isolation rather
than behaviour.
"""

import unittest
from pathlib import Path

from agents import bootstrap
from tools import enrich as enrich_tools, reminder as reminder_tools


class AgentStructureTests(unittest.TestCase):
    def test_specialist_tool_specs_match_registered_handlers(self):
        for specialist in (enrich_tools, reminder_tools):
            with self.subTest(specialist=specialist.__name__):
                advertised = {
                    spec["function"]["name"] for spec in specialist.TOOL_SPECS
                }
                self.assertLessEqual(advertised, set(specialist.TOOLS))
                self.assertLessEqual(specialist.WRITE_TOOLS, advertised)

        self.assertNotIn("create_reminder", enrich_tools.TOOLS)
        self.assertNotIn("create_reminder", {
            spec["function"]["name"] for spec in enrich_tools.TOOL_SPECS
        })

    def test_the_agent_layout(self):
        root = Path(__file__).parents[1] / "agents"
        expected = {
            "enrich/state.py",
            "enrich/graph.py", "enrich/routing.py",
            "enrich/agent.py",
            "enrich/prompts.py",
            "enrich/nodes/reason.py", "enrich/nodes/plan.py",
            "enrich/nodes/act.py", "enrich/nodes/approve.py",
            "enrich/nodes/classify/gather.py", "enrich/nodes/classify/propose.py",
            "enrich/nodes/classify/normalize.py",
            "enrich/nodes/write/link.py", "enrich/nodes/write/stage.py",
            "enrich/nodes/write/validate.py",
            "reminder/graph.py", "reminder/state.py",
            "reminder/prompts.py", "reminder/agent.py",
            "reminder/nodes/resolve.py", "reminder/nodes/build.py",
            "finder/agent.py", "finder/graph.py", "finder/routing.py",
            "finder/state.py", "finder/prompts.py",
            "finder/nodes/reason.py", "finder/nodes/act.py",
            "responder/agent.py", "responder/prompts.py",
            "router/__init__.py", "router/agent.py", "router/prompts.py",
            "runtime/loop.py", "runtime/registry.py",
            "runtime/state_store.py", "runtime/execution_ledger.py",
            "runtime/checkpoint.py",
            "runtime/model_gateway.py", "runtime/execute_tool.py",
            "contracts/__init__.py", "contracts/status.py",
            "contracts/user_context.py", "contracts/ref.py",
            "contracts/history_entry.py", "contracts/agent_request.py",
            "contracts/agent_result.py", "contracts/agent_spec.py",
            "contracts/turn_outcome.py", "contracts/plan_request.py",
            "contracts/tool_result.py",
            "bootstrap.py",
            "../common/__init__.py", "../common/embedings.py", "../common/helper.py",
            "../tools/__init__.py",
            "../tools/finder/__init__.py",
            "../tools/finder/specs.py",
            "../tools/finder/db.py",
            "../tools/finder/search_notes.py",
            "../tools/finder/get_note.py",
            "../tools/finder/neighbors.py",
            "../tools/finder/list_reminders.py",
            "../tools/finder/list_agenda.py",
            "../tools/finder/list_paths.py",
            "../tools/finder/detect_reminder.py",
            "../tools/enrich/__init__.py",
            "../tools/enrich/db.py",
            "../tools/enrich/specs.py",
            "../tools/enrich/list_paths.py",
            "../tools/enrich/list_tags.py",
            "../tools/enrich/get_note_context.py",
            "../tools/enrich/get_vault_context.py",
            "../tools/enrich/find_related_notes.py",
            "../tools/enrich/create_note.py",
            "../tools/enrich/set_note_path.py",
            "../tools/enrich/add_note_tags.py",
            "../tools/enrich/enrich_note.py",
            "../tools/reminder/create_reminder.py",
            "../tools/reminder/specs.py", "../tools/reminder/db.py",
            "../tools/reminder/get_note_context.py",
            "../tools/responder/__init__.py",
            "../tools/responder/db.py",
            "../tools/responder/read_state.py",
        }
        self.assertEqual(set(), {path for path in expected if not (root / path).is_file()})
        self.assertEqual([], list((root / "enrich" / "tools").rglob("*.py")))
        self.assertEqual([], list((root / "knowledge").rglob("*.py")))

    def test_the_replaced_handoff_path_is_gone(self):
        """The loop replaced it. Left behind, the old dispatch would be a
        second way to reach a specialist — and the one that let an agent name a
        peer. The `handoff_api` modules went the same way: with no handoff left
        to serve, planning belongs in the agent that pauses on it."""
        root = Path(__file__).parents[1]

        for gone in ("agents/conversation", "agents/runtime/handoff_dispatch.py",
                     "agents/runtime/specialist_registry.py", "api/chat",
                     "tools/conversation", "agents/enrich/handoff_api.py",
                     "agents/reminder/handoff_api.py"):
            with self.subTest(gone=gone):
                self.assertFalse((root / gone).exists())

    def test_the_contracts_sit_at_the_bottom_of_the_graph(self):
        """A contract may import its own package and the standard library, and
        nothing else.

        This is the property the whole farm rests on: four agents, the loop, the
        router and the store agree on shapes without importing each other,
        because the shapes depend on none of them. One import of an agent, a
        tool, or the loop from here would make that a cycle."""
        root = Path(__file__).parents[1] / "agents" / "contracts"
        reaching = []

        for path in root.glob("*.py"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.startswith(("import ", "from ")):
                    continue

                if line.startswith("from agents.contracts"):
                    continue

                if "agents." in line or "tools." in line or line.startswith(
                        ("import db", "from db ", "import config", "from config ")):
                    reaching.append(f"{path.name}: {line.strip()}")

        self.assertEqual([], reaching)

    def test_every_contract_module_holds_one_type(self):
        """The package is one type per file, so a reader finds `AgentSpec` in
        `agent_spec.py` without opening anything else."""
        root = Path(__file__).parents[1] / "agents" / "contracts"

        for path in root.glob("*.py"):
            if path.name == "__init__.py":
                continue

            declared = [
                line for line in path.read_text(encoding="utf-8").splitlines()
                if line.startswith("class ") or (
                    line and not line[0].isspace() and " = " in line
                    and not line.startswith(("from ", "import ")))
            ]

            with self.subTest(module=path.name):
                self.assertEqual(1, len(declared), declared)

    def test_routing_and_the_loop_do_not_import_each_other(self):
        """Neither half of the split may reach for the other.

        `agents/router/` decides who runs next; `agents/runtime/loop.py` runs
        them. They meet only in `bootstrap.py`, which hands the router to the
        loop as a parameter — that is what lets a routing rule change without
        touching the loop, and the reverse. An import either way would collapse
        the split back into one module with two reasons to change.

        Only the loop machinery is off limits, not all of `runtime/`: the rest
        of that package is shared infrastructure, and case 3 reaching
        `model_gateway` is exactly what it is there for."""
        root = Path(__file__).parents[1] / "agents"
        loop_machinery = ("agents.runtime.loop", "agents.runtime.registry",
                          "agents.runtime.state_store")
        offending = []

        for line in (root / "runtime" / "loop.py").read_text(
                encoding="utf-8").splitlines():
            if line.startswith(("import ", "from ")) and "agents.router" in line:
                offending.append(f"runtime/loop.py: {line.strip()}")

        for path in (root / "router").glob("*.py"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.startswith(("import ", "from ")):
                    continue

                if any(module in line for module in loop_machinery):
                    offending.append(f"router/{path.name}: {line.strip()}")

        self.assertEqual([], offending)

    def test_no_agent_names_another_agent(self):
        """The whole point of the farm: routing is the loop's, so an agent
        module that imports a sibling has re-introduced the coupling. Only
        `bootstrap.py` may name them, because naming them is its job."""
        root = Path(__file__).parents[1] / "agents"
        peers = ("enrich", "reminder", "finder", "responder")
        offending = []

        for path in root.rglob("*.py"):
            owner = path.relative_to(root).parts[0]

            if owner not in peers:
                continue

            for line in path.read_text(encoding="utf-8").splitlines():
                for peer in peers:
                    if peer != owner and f"agents.{peer}" in line:
                        offending.append(f"{path.relative_to(root)}: {line.strip()}")

        self.assertEqual([], offending)

    def test_agents_reach_persistence_only_through_tools(self):
        """No agent owns SQL, and none reaches into a tool's database module.
        Every read and write goes through `execute_tool`; thread state belongs
        to the calling section (`api/chat_v2`).

        Two modules are exempt, and both are infrastructure rather than an
        agent's domain data: `runtime/execution_ledger.py` (at-most-once
        bookkeeping) and `runtime/state_store.py` (the turn tree). Neither is
        imported by an agent — the composition root hands them to the loop."""
        root = Path(__file__).parents[1] / "agents"
        self.assertEqual(
            [],
            [str(path.relative_to(root)) for path in root.rglob("db.py")],
        )

        reaching = []

        for path in root.rglob("*.py"):
            if path.name in {"execution_ledger.py", "state_store.py"}:
                continue

            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith(("from db import", "import db")) or (
                        line.startswith("from tools.") and line.endswith(" import db")):
                    reaching.append(f"{path.relative_to(root)}: {line}")

        self.assertEqual([], reaching)

    def test_every_agent_is_registered_with_the_farm(self):
        for name in ("enrich", "reminder", "finder", "responder"):
            with self.subTest(agent=name):
                self.assertEqual(name, bootstrap.router.get_agent(name).name)

    def test_the_responder_is_never_a_routing_candidate(self):
        """It takes the last hop by construction; offering it to the model as a
        peer would let a turn answer without doing anything."""
        self.assertNotIn("responder", {
            agent["name"] for agent in bootstrap.agents.list_agents()
        })


if __name__ == "__main__":
    unittest.main()
