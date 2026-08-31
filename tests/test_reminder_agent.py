"""Reminder-agent domain integration boundaries."""

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from agents.reminder import domain, tools


class ReminderAgentTests(unittest.TestCase):
    def test_hint_gate_skips_model_for_ordinary_note(self):
        now = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
        with patch.object(domain, "get_client") as client:
            self.assertIsNone(domain.extract_time("A plain project thought", now))
        client.assert_not_called()

    def test_referenced_note_reminder_attaches_without_creating_duplicate_note(self):
        action = {"name": "create_reminder", "args": {
            "text": "Follow up on roadmap", "note_id": 20,
            "remind_at": "2026-09-01T09:00:00+00:00",
        }}
        attached = {"note_id": 20, "reminder_id": 3,
                    "remind_at": "2026-09-01T09:00:00+00:00"}
        with patch.object(tools.domain, "attach", return_value=attached) as attach, \
                patch.object(tools.domain, "create") as create:
            result = tools.execute(7, action)

        self.assertIn('"note_id": 20', result)
        attach.assert_called_once()
        create.assert_not_called()

if __name__ == "__main__":
    unittest.main()
