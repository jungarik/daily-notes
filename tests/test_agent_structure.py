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
            "conversation/domain.py", "conversation/db.py",
            "conversation/tools/specs.py", "conversation/tools/handlers.py",
            "conversation/tools/db.py",
            "conversation/nodes/model.py", "conversation/nodes/read.py",
            "conversation/nodes/dispatch.py", "conversation/nodes/approval.py",
            "conversation/nodes/final.py", "enrich/api.py", "enrich/state.py",
            "enrich/graph.py", "enrich/routing.py", "enrich/domain.py",
            "enrich/db.py",
            "enrich/prompts.py",
            "enrich/tools/specs.py", "enrich/tools/handlers.py",
            "enrich/nodes/model.py", "enrich/nodes/read.py",
            "enrich/nodes/metadata.py",
            "enrich/nodes/reminder.py",
            "enrich/nodes/write.py", "enrich/nodes/approval.py",
            "enrich/nodes/final.py", "bootstrap.py",
        }
        self.assertEqual(set(), {path for path in expected if not (root / path).is_file()})
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
