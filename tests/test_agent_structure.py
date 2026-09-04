"""Guard the simplified two-agent architecture."""

import unittest
from pathlib import Path

from agents import bootstrap, conversation
from agents.enrich import api as enrich


class AgentStructureTests(unittest.TestCase):
    def test_two_agent_structure(self):
        root = Path(__file__).parents[1] / "agents"
        expected = {
            "conversation/api.py", "conversation/state.py", "conversation/graph.py",
            "conversation/routing.py", "conversation/prompts.py",
            "conversation/db.py",
            "conversation/nodes/reason.py", "conversation/nodes/act.py",
            "conversation/nodes/handoff.py", "conversation/nodes/approve.py",
            "enrich/api.py", "enrich/state.py",
            "enrich/graph.py", "enrich/routing.py",
            "enrich/db.py",
            "enrich/prompts.py",
            "enrich/nodes/reason.py", "enrich/nodes/plan.py",
            "enrich/nodes/act.py", "enrich/nodes/approve.py",
            "enrich/nodes/classify/gather.py", "enrich/nodes/classify/propose.py",
            "enrich/nodes/classify/normalize.py",
            "enrich/nodes/schedule/resolve.py", "enrich/nodes/schedule/build.py",
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
            "../tools/enrich/create_reminder.py",
        }
        self.assertEqual(set(), {path for path in expected if not (root / path).is_file()})
        self.assertEqual([], list((root / "conversation" / "tools").rglob("*.py")))
        self.assertEqual([], list((root / "enrich" / "tools").rglob("*.py")))
        self.assertEqual([], list((root / "knowledge").rglob("*.py")))
        self.assertEqual([], list((root / "reminder").rglob("*.py")))

    def test_public_facades_and_registry(self):
        self.assertTrue(callable(conversation.start_turn))
        self.assertTrue(callable(conversation.confirm))
        self.assertTrue(callable(conversation.evaluate_turn))
        self.assertTrue(callable(enrich.plan_action))
        self.assertTrue(callable(enrich.execute_action))
        self.assertTrue(callable(enrich.propose_capture))
        self.assertTrue(callable(enrich.confirm_capture))
        self.assertIs(bootstrap.registry.get("enrich"), enrich)


if __name__ == "__main__":
    unittest.main()
