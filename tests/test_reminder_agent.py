"""Reminder-agent domain integration boundaries."""

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from agents.reminder import domain


class ReminderAgentTests(unittest.TestCase):
    def test_hint_gate_skips_model_for_ordinary_note(self):
        now = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
        with patch.object(domain, "get_client") as client:
            self.assertIsNone(domain.extract_time("A plain project thought", now))
        client.assert_not_called()

if __name__ == "__main__":
    unittest.main()
