"""Tests for stable ids on pending actions created before the ledger existed."""

import unittest
from unittest.mock import patch

from agents.chat import service as chat_service
from agents.enrich import service as enrich_service


class ActionCheckpointTests(unittest.TestCase):
    def test_chat_legacy_pending_id_is_stable_and_saved_before_execution(self):
        pending = {
            "tool_call_id": "call-1",
            "agent": "reminder",
            "action": {"name": "create_reminder", "args": {"text": "Call"}},
        }
        with patch.object(chat_service.chat_store, "save_thread") as save:
            first = chat_service._checkpoint_action_id(12, [], pending)
            second = chat_service._checkpoint_action_id(12, [], pending)

        self.assertEqual(first["action_id"], second["action_id"])
        self.assertNotIn("action_id", pending)
        self.assertEqual(2, save.call_count)

    def test_enrich_legacy_pending_id_is_stable(self):
        pending = {"tool_call_id": "call-2", "name": "create_note",
                   "args": {"text": "Idea"}, "summary": "Create note"}
        with patch.object(enrich_service.db, "save_thread"):
            first = enrich_service._checkpoint_action_id(13, [], pending)
            second = enrich_service._checkpoint_action_id(13, [], pending)

        self.assertEqual(first["action_id"], second["action_id"])


if __name__ == "__main__":
    unittest.main()
