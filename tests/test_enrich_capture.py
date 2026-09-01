"""Standalone Enrich fast-capture flow."""

import json
import unittest
from unittest.mock import patch

from agents.enrich import api as enrich


class EnrichCaptureTests(unittest.TestCase):
    def setUp(self):
        self.meta = {"type": "idea", "title": "Pocket garden", "path": "Projects",
                     "tags": ["garden"], "priority": "low"}
        self.related = [{"note_id": 9, "note_type": "note", "title": "Balcony",
                         "path": "Areas", "tags": ["garden"], "distance": 0.2}]

    def analysis(self):
        return {"metadata": self.meta,
                "metadata_context": {"related_notes": self.related},
                "metadata_trace": [{"node": "metadata_validation", "status": "ok"}]}

    def test_propose_returns_editable_preview_without_writing(self):
        with patch.object(enrich.METADATA_GRAPH, "invoke", return_value=self.analysis()):
            proposal = enrich.propose_capture(7, "Build a pocket garden")

        self.assertEqual("proposed", proposal["status"])
        self.assertEqual("capture_thought", proposal["action"]["name"])
        self.assertEqual("Pocket garden", proposal["action"]["args"]["title"])
        self.assertEqual([], proposal["action"]["args"]["linked_note_ids"])
        self.assertEqual(9, proposal["related_notes"][0]["note_id"])

    def test_revision_is_validated_and_gets_a_new_action_id(self):
        with patch.object(enrich.METADATA_GRAPH, "invoke", return_value=self.analysis()):
            original = enrich.propose_capture(7, "Build a pocket garden")
        with patch.object(enrich.helper, "localized_roots",
                          return_value=({"Projects": "projects"}, "Projects")), \
                patch.object(enrich.db, "get_note_for_user",
                             return_value={"id": 9}):
            revised = enrich.revise_capture(
                7, original, {"path": "Projects/Garden", "linked_note_ids": [9]})

        self.assertNotEqual(original["action_id"], revised["action_id"])
        self.assertEqual("Projects/Garden", revised["action"]["args"]["path"])
        self.assertEqual([9], revised["action"]["args"]["linked_note_ids"])

    def test_revision_rejects_another_users_link(self):
        with patch.object(enrich.METADATA_GRAPH, "invoke", return_value=self.analysis()):
            proposal = enrich.propose_capture(7, "Build a pocket garden")
        with patch.object(enrich.helper, "localized_roots",
                          return_value=({"Projects": "projects"}, "Projects")), \
                patch.object(enrich.db, "get_note_for_user", return_value=None):
            with self.assertRaises(ValueError):
                enrich.revise_capture(7, proposal, {"linked_note_ids": [99]})

    def test_confirm_uses_idempotency_ledger(self):
        with patch.object(enrich.METADATA_GRAPH, "invoke", return_value=self.analysis()):
            proposal = enrich.propose_capture(7, "Build a pocket garden")
        with patch.object(enrich.execution_ledger, "execute_once",
                          return_value=json.dumps({"note_id": 12,
                                                   "linked_note_ids": [9]})) as once:
            result = enrich.confirm_capture(7, proposal)

        self.assertEqual("completed", result["status"])
        self.assertEqual(12, result["note_id"])
        self.assertEqual(proposal["action_id"], once.call_args.args[0])
        self.assertEqual("enrich", once.call_args.args[2])

    def test_cancel_does_not_execute(self):
        proposal = {"action_id": "capture-1"}
        self.assertEqual({"status": "cancelled", "action_id": "capture-1"},
                         enrich.cancel_capture(proposal))


if __name__ == "__main__":
    unittest.main()
