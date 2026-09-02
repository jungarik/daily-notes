"""Reminder capability graph and domain integration boundaries."""

import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agents.enrich import api as enrich_service
from agents.enrich.nodes import reminder
from tools.enrich import create_reminder


class ReminderAgentTests(unittest.TestCase):
    def test_hint_gate_skips_model_for_ordinary_note(self):
        now = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
        with patch.object(reminder.model_gateway, "chat_completion") as client:
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

        with patch.object(reminder.model_gateway, "chat_completion",
                          side_effect=client.chat.completions.create):
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
        with patch.object(create_reminder.db, "save_note") as save_note, \
                patch.object(create_reminder.db, "attach_reminder",
                             return_value=3) as attach:
            result = enrich_service.execute_action(
                7, action, datetime.now(timezone.utc), timezone.utc, "en")

        self.assertIn('"note_id": 20', result)
        attach.assert_called_once_with(
            7, 20, datetime.fromisoformat("2026-09-01T09:00:00+00:00"))
        save_note.assert_not_called()

    def test_standalone_reminder_creates_note_before_attaching_reminder(self):
        action = {"name": "create_reminder", "args": {
            "text": "Call mom tomorrow",
            "remind_at": "2026-09-01T09:00:00+00:00",
        }}
        with patch.object(create_reminder.db, "save_note", return_value=30) as save_note, \
                patch.object(create_reminder.db, "save_chunks") as save_chunks, \
                patch.object(create_reminder.embedings, "build_chunks", return_value=[]) as chunks, \
                patch.object(create_reminder.db, "attach_reminder", return_value=4) as attach:
            result = enrich_service.execute_action(
                7, action, datetime.now(timezone.utc), timezone.utc, "en")

        self.assertIn('"note_id": 30', result)
        save_note.assert_called_once_with(7, "Call mom tomorrow")
        chunks.assert_called_once_with("Call mom tomorrow")
        save_chunks.assert_called_once_with(30, [])
        attach.assert_called_once_with(
            7, 30, datetime.fromisoformat("2026-09-01T09:00:00+00:00"))

if __name__ == "__main__":
    unittest.main()
