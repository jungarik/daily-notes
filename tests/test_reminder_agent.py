"""Reminder capability graph and domain integration boundaries."""

import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agents.enrich import domain
from agents.enrich import api as enrich_service
from agents.enrich.nodes import reminder
from agents.enrich.tools import handlers


class ReminderAgentTests(unittest.TestCase):
    def test_hint_gate_skips_model_for_ordinary_note(self):
        now = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
        with patch.object(reminder.openai_client, "get_client") as client:
            result = reminder.extract_time({
                "contract": {"instruction": "A plain project thought"},
                "now": now,
                "reminder_trace": [],
            })

        self.assertEqual({"is_reminder": False, "remind_at": None},
                         result["reminder_raw"])
        client.assert_not_called()

    def test_reminder_model_node_extracts_time(self):
        now = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
        payload = {"is_reminder": True,
                   "remind_at": "2026-09-01T09:00:00+00:00"}
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=Mock(return_value=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(
                    content=json.dumps(payload)))])))))

        with patch.object(reminder.openai_client, "get_client", return_value=client):
            result = reminder.extract_time({
                "contract": {"instruction": "Call tomorrow"},
                "now": now,
                "reminder_trace": [],
            })

        self.assertEqual(payload, result["reminder_raw"])
        self.assertEqual("reminder_model", result["reminder_trace"][0]["node"])

    def test_referenced_note_reminder_attaches_without_creating_duplicate_note(self):
        action = {"name": "create_reminder", "args": {
            "text": "Follow up on roadmap", "note_id": 20,
            "remind_at": "2026-09-01T09:00:00+00:00",
        }}
        attached = {"note_id": 20, "reminder_id": 3,
                    "remind_at": "2026-09-01T09:00:00+00:00"}
        with patch.object(handlers.d, "attach_reminder", return_value=attached) as attach, \
                patch.object(handlers.d, "create_reminder") as create:
            result = enrich_service.execute_action(
                7, action, datetime.now(timezone.utc), timezone.utc, "en")

        self.assertIn('"note_id": 20', result)
        attach.assert_called_once()
        create.assert_not_called()

if __name__ == "__main__":
    unittest.main()
