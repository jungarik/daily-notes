"""Tests for stable ids on pending actions created before the ledger existed."""

import unittest

from agents.conversation import api as chat_service


class ActionCheckpointTests(unittest.TestCase):
    def test_chat_legacy_pending_id_is_stable_and_leaves_input_untouched(self):
        pending = {
            "tool_call_id": "call-1",
            "agent": "reminder",
            "action": {"name": "create_reminder", "args": {"text": "Call"}},
        }
        first = chat_service._with_action_id(12, pending)
        second = chat_service._with_action_id(12, pending)

        self.assertEqual(first["action_id"], second["action_id"])
        self.assertNotIn("action_id", pending)
        self.assertEqual("call-1", first["tool_call_id"])


if __name__ == "__main__":
    unittest.main()
