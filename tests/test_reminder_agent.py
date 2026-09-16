"""Reminder capability graph and domain integration boundaries."""

import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agents.reminder import handoff_api as reminder_service
from agents.reminder.nodes import resolve as reminder_resolve
from tools.reminder import create_reminder
from agents.runtime.events import append, failed


class ReminderAgentTests(unittest.TestCase):
    def test_hint_gate_skips_model_for_ordinary_note(self):
        now = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
        with patch.object(reminder_resolve.model_gateway, "chat_completion") as client:
            result = reminder_resolve.run({
                "contract": {"instruction": "A plain project thought"},
                "now": now,
                "events": [],
            })

        self.assertEqual({"is_reminder": False, "remind_at": None},
                         result["extracted_time"])
        client.assert_not_called()

    def test_reminder_model_node_extracts_time(self):
        now = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
        payload = {"is_reminder": True,
                   "remind_at": "2026-09-01T09:00:00+00:00"}
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=Mock(return_value=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(
                    content=json.dumps(payload)))])))))

        with patch.object(reminder_resolve.model_gateway, "chat_completion",
                          side_effect=client.chat.completions.create):
            result = reminder_resolve.run({
                "contract": {"instruction": "Call tomorrow"},
                "now": now,
                "events": [],
            })

        self.assertEqual(payload, result["extracted_time"])
        self.assertEqual(
            [{"kind": "node", "node": "resolve", "status": "ok"}],
            result["events"])

    def test_referenced_note_reminder_attaches_without_creating_duplicate_note(self):
        action = {"name": "create_reminder", "args": {
            "text": "Follow up on roadmap", "note_id": 20,
            "remind_at": "2026-09-01T09:00:00+00:00",
        }}
        with patch.object(create_reminder.db, "save_note") as save_note, \
                patch.object(create_reminder.db, "attach_reminder",
                             return_value=3) as attach:
            result = reminder_service.execute_action(
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
            result = reminder_service.execute_action(
                7, action, datetime.now(timezone.utc), timezone.utc, "en")

        self.assertIn('"note_id": 30', result)
        save_note.assert_called_once_with(7, "Call mom tomorrow")
        chunks.assert_called_once_with("Call mom tomorrow")
        save_chunks.assert_called_once_with(30, [])
        attach.assert_called_once_with(
            7, 30, datetime.fromisoformat("2026-09-01T09:00:00+00:00"))

if __name__ == "__main__":
    unittest.main()


class ReminderEventChannelTests(unittest.TestCase):
    """The event list is a reducer channel: a node emits only its own entries."""

    def test_a_node_emits_only_what_it_did(self):
        now = datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc)
        patch = reminder_resolve.run({
            "contract": {"instruction": "A plain project thought"},
            "now": now,
            "events": [{"kind": "node", "node": "earlier", "status": "ok"}],
        })

        self.assertEqual(
            [{"kind": "node", "node": "resolve", "status": "skipped"}],
            patch["events"])

    def test_the_reducer_appends_rather_than_replaces(self):
        self.assertEqual(
            [{"node": "a"}, {"node": "b"}],
            append([{"node": "a"}], [{"node": "b"}]))

    def test_a_failure_is_an_event_not_a_key(self):
        now = datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc)
        with patch.object(reminder_resolve.model_gateway, "chat_completion",
                          side_effect=RuntimeError("provider down")):
            result = reminder_resolve.run({
                "contract": {"instruction": "Call tomorrow"},
                "now": now,
                "events": [],
            })

        self.assertNotIn("reminder_error", result)
        self.assertEqual("error", result["events"][0]["status"])
        self.assertIn("provider down", result["events"][0]["error"])
        self.assertTrue(failed(result["events"], "resolve"))
