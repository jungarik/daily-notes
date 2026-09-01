"""Regression tests for confirmed-write idempotency."""

import unittest
from unittest.mock import Mock, call, patch

from agents.runtime import execution_ledger as action_execution


class ActionExecutionTests(unittest.TestCase):
    def setUp(self):
        self.action = {"name": "create_reminder", "args": {"text": "Call"}}

    def test_new_action_is_completed_before_result_returns(self):
        events = []
        execute = Mock(side_effect=lambda: events.append("write") or "created")

        with patch.object(action_execution, "claim", return_value={"status": "claimed"}), \
                patch.object(action_execution, "complete",
                             side_effect=lambda *args: events.append("checkpoint")) as complete:
            result = action_execution.execute_once(
                "action-1", 7, "reminder", self.action, execute)

        self.assertEqual("created", result)
        self.assertEqual(["write", "checkpoint"], events)
        complete.assert_called_once_with("action-1", 7, "created")

    def test_completed_action_reuses_result_without_write(self):
        execute = Mock()
        with patch.object(action_execution, "claim", return_value={
                "status": "completed", "result": "already created", "error": None}), \
                patch.object(action_execution, "complete") as complete:
            result = action_execution.execute_once(
                "action-1", 7, "reminder", self.action, execute)

        self.assertEqual("already created", result)
        execute.assert_not_called()
        complete.assert_not_called()

    def test_concurrent_or_failed_action_is_not_retried(self):
        execute = Mock()
        records = [
            {"status": "executing", "result": None, "error": None},
            {"status": "failed", "result": None, "error": "connection lost"},
        ]
        with patch.object(action_execution, "claim", side_effect=records):
            first = action_execution.execute_once(
                "action-1", 7, "reminder", self.action, execute)
            second = action_execution.execute_once(
                "action-1", 7, "reminder", self.action, execute)

        self.assertIn("already being processed", first)
        self.assertIn("was not retried", second)
        execute.assert_not_called()

    def test_uncertain_write_failure_is_recorded_and_raised(self):
        execute = Mock(side_effect=RuntimeError("connection lost"))
        with patch.object(action_execution, "claim", return_value={"status": "claimed"}), \
                patch.object(action_execution, "fail") as fail:
            with self.assertRaisesRegex(RuntimeError, "connection lost"):
                action_execution.execute_once(
                    "action-1", 7, "enrich", self.action, execute)

        fail.assert_has_calls([call("action-1", 7, "connection lost")])


if __name__ == "__main__":
    unittest.main()
