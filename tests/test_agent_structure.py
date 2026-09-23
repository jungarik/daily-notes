"""Guard the simplified two-agent architecture."""

import unittest
from pathlib import Path

from agents import bootstrap, conversation
from agents.enrich import handoff_api as enrich_handoff
from agents.reminder import handoff_api as reminder_handoff
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

    def test_two_agent_structure(self):
        root = Path(__file__).parents[1] / "agents"
        expected = {
            "conversation/api.py", "conversation/state.py", "conversation/graph.py",
            "conversation/routing.py", "conversation/prompts.py",
            "conversation/nodes/reason.py", "conversation/nodes/act.py",
            "conversation/nodes/handoff.py", "conversation/nodes/approve.py",
            "enrich/state.py",
            "enrich/graph.py", "enrich/routing.py",
            "enrich/handoff_api.py", "enrich/agent.py",
            "enrich/prompts.py",
            "enrich/nodes/reason.py", "enrich/nodes/plan.py",
            "enrich/nodes/act.py", "enrich/nodes/approve.py",
            "enrich/nodes/classify/gather.py", "enrich/nodes/classify/propose.py",
            "enrich/nodes/classify/normalize.py",
            "reminder/handoff_api.py", "reminder/graph.py", "reminder/state.py",
            "reminder/prompts.py", "reminder/agent.py",
            "reminder/nodes/resolve.py", "reminder/nodes/build.py",
            "responder/agent.py", "responder/prompts.py",
            "broker/__init__.py", "broker/contracts.py", "broker/broker.py",
            "broker/registry.py", "broker/state_store.py",
            "broker/router.py",
            "enrich/nodes/write/link.py", "enrich/nodes/write/stage.py",
            "enrich/nodes/write/validate.py", "bootstrap.py",
            "runtime/execute_tool.py",
            "../common/__init__.py", "../common/embedings.py", "../common/helper.py",
            "../tools/__init__.py",
            "../tools/conversation/__init__.py",
            "../tools/conversation/specs.py",
            "../tools/conversation/db.py",
            "../tools/conversation/search_notes.py",
            "../tools/conversation/get_note.py",
            "../tools/conversation/neighbors.py",
            "../tools/conversation/list_reminders.py",
            "../tools/conversation/list_agenda.py",
            "../tools/conversation/list_paths.py",
            "../tools/conversation/detect_reminder.py",
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
        }
        self.assertEqual(set(), {path for path in expected if not (root / path).is_file()})
        self.assertEqual([], list((root / "conversation" / "tools").rglob("*.py")))
        self.assertEqual([], list((root / "enrich" / "tools").rglob("*.py")))
        self.assertEqual([], list((root / "knowledge").rglob("*.py")))

    def test_agents_reach_persistence_only_through_tools(self):
        """No agent owns SQL, and none reaches into a tool's database module.
        Every read and write goes through `execute_tool`; thread state belongs
        to the calling section (`api/chat`).

        Two modules are exempt, and both are infrastructure rather than an
        agent's domain data: `runtime/execution_ledger.py` (at-most-once
        bookkeeping) and `broker/state_store.py` (the turn tree). Neither is
        imported by an agent — the composition root hands them to the broker."""
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

    def test_public_facades_and_registry(self):
        self.assertTrue(callable(conversation.run_turn))
        self.assertTrue(callable(conversation.run_confirmation))
        self.assertTrue(callable(conversation.evaluate_turn))
        self.assertTrue(callable(enrich_handoff.plan_action))
        self.assertTrue(callable(enrich_handoff.execute_action))
        self.assertIs(bootstrap.registry.get("enrich"), enrich_handoff)
        self.assertTrue(callable(reminder_handoff.plan_action))
        self.assertTrue(callable(reminder_handoff.execute_action))
        self.assertIs(bootstrap.registry.get("reminder"), reminder_handoff)


if __name__ == "__main__":
    unittest.main()
