"""Evaluation runner, trace, and metric regressions."""

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

from agents.conversation.state import ConversationContext as Ctx
from api.evals import helper
from api.evals import endpoints
from api.evals import db as eval_db


class EvaluationTests(unittest.TestCase):
    def test_metrics_aggregate_requested_observability_fields(self):
        rows = [
            {"task_success": "yes", "groundedness": "good", "latency_ms": 100,
             "errors": "none"},
            {"task_success": "partial", "groundedness": "partial", "latency_ms": 200,
             "errors": "missing_context"},
            {"task_success": "no", "groundedness": "bad", "latency_ms": 300,
             "errors": "wrong_retrieval"},
        ]
        with patch.object(helper.db, "metric_rows", return_value=rows):
            metrics = helper.metrics(7, run_id=4)

        self.assertEqual(3, metrics["total_cases"])
        self.assertEqual(0.3333, metrics["success_rate"])
        self.assertEqual(200, metrics["average_latency_ms"])
        self.assertEqual(300, metrics["max_latency_ms"])
        self.assertEqual("none", metrics["top_error_types"][0]["error"])

    def test_disabled_judge_keeps_runtime_observation_without_grades(self):
        case = {"thread_id": 9, "turn_index": 1, "agent": "reminder",
                "question": "Remind me tomorrow",
                "expected_behavior": "Propose a reminder."}
        action = {"name": "create_reminder", "args": {"text": "x"},
                  "summary": "Create reminder"}
        now = datetime(2026, 8, 31, tzinfo=timezone.utc)
        with patch.object(helper.config, "AGENT_EVAL_JUDGE_ENABLED", False), \
                patch.object(helper.enrich_service, "plan_action", return_value=action):
            result = helper._run_case(case, 7, now, timezone.utc, "en")

        self.assertIsNone(result["task_success"])
        self.assertEqual("tool", result["route_or_mode"])
        self.assertEqual("create_reminder", result["tools_used"])
        self.assertEqual("none", result["errors"])

    def test_thread_turn_selection_defaults_to_latest_completed(self):
        messages = [
            {"role": "system", "content": "old"},
            {"role": "user", "content": "First"},
            {"role": "assistant", "content": "First answer"},
            {"role": "user", "content": "Second"},
            {"role": "assistant", "content": None, "tool_calls": [{
                "function": {"name": "set_reminder",
                             "arguments": '{"instruction":"Tomorrow at nine"}'}}]},
            {"role": "tool", "content": "created"},
            {"role": "assistant", "content": "Scheduled"},
            {"role": "user", "content": "Still pending"},
        ]
        selected = helper._completed_turn(messages, None)
        self.assertEqual(2, selected["turn_index"])
        self.assertEqual("Tomorrow at nine",
                         helper._handoff_instruction(selected, "reminder"))

    def test_requested_incomplete_turn_is_rejected(self):
        messages = [{"role": "user", "content": "Pending"},
                    {"role": "assistant", "content": None, "tool_calls": []}]
        with self.assertRaises(LookupError):
            helper._completed_turn(messages, 1)

    def test_run_persists_result_against_thread_and_turn(self):
        thread = {"messages": [{"role": "user", "content": "Question"},
                               {"role": "assistant", "content": "Old answer"}],
                  "pending": None}
        observed = {"thread_id": 42, "turn_index": 1, "agent": "chat",
                    "question": "Question", "expected_behavior": "Be grounded",
                    "answer": "New answer", "retrieved_chunks": "[]",
                    "route_or_mode": "RAG", "tools_used": "search_notes",
                    "task_success": "yes", "groundedness": "good",
                    "answer_quality": "good", "latency_ms": 10,
                    "errors": "none", "notes": "", "trace": {}}
        with patch.object(helper.db, "get_thread", return_value=thread), \
                patch.object(helper.db, "create_run", return_value=8) as create_run, \
                patch.object(helper, "_settings", return_value=(timezone.utc, "en")), \
                patch.object(helper, "_run_case", return_value=observed), \
                patch.object(helper.db, "save_result") as save_result, \
                patch.object(helper.db, "finish_run"), \
                patch.object(helper, "metrics", return_value={"total_cases": 1}):
            result = helper.run(7, 42, "Be grounded", "chat", 1)

        create_run.assert_called_once_with(
            7, 42, 1, "chat", "Be grounded", helper.config.AGENT_EVAL_JUDGE_ENABLED)
        save_result.assert_called_once_with(8, observed)
        self.assertEqual(1, result["total_cases"])

    def test_metrics_do_not_report_false_zero_rates_when_judge_is_disabled(self):
        rows = [{"task_success": None, "groundedness": None,
                 "latency_ms": 80, "errors": "none"}]
        with patch.object(helper.db, "metric_rows", return_value=rows):
            metrics = helper.metrics(7, run_id=5)

        self.assertEqual(0, metrics["judged_cases"])
        self.assertIsNone(metrics["success_rate"])
        self.assertIsNone(metrics["groundedness_good_rate"])

    def test_chat_context_collects_structured_trace(self):
        ctx = Ctx(7, datetime.now(timezone.utc), timezone.utc, "en")
        ctx.record_tool("get_note", {"note_id": 3}, '{"id":3}')
        ctx.record_route("tool")
        self.assertEqual("get_note", ctx.trace["tools"][0]["name"])
        self.assertEqual(["tool"], ctx.trace["routes"])

    def test_eval_api_is_protected_and_authorizes_internal_user_id(self):
        self.assertTrue(endpoints.router.dependencies)
        with patch.object(endpoints.db, "is_eval_admin", return_value=True):
            self.assertEqual(7, endpoints.eval_admin_user(7))
        with patch.object(endpoints.db, "is_eval_admin", return_value=False):
            with self.assertRaises(HTTPException) as raised:
                endpoints.eval_admin_user(7)
        self.assertEqual(403, raised.exception.status_code)

    def test_eval_admin_uses_internal_user_ids(self):
        cur = MagicMock()
        cur.fetchall.return_value = [(7,), (9,)]
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cur
        with patch.object(eval_db.config, "EVAL_ADMIN_USER_IDS", {7}), \
                patch.object(eval_db, "cursor", return_value=cursor_context):
            self.assertTrue(eval_db.is_eval_admin(7))
            self.assertFalse(eval_db.is_eval_admin(8))
        cur.execute.assert_called_with(
            "SELECT id FROM users WHERE id = ANY(%s);", ([7],))

    def test_metric_queries_do_not_use_untyped_nullable_parameters(self):
        cur = MagicMock()
        cur.fetchone.side_effect = [(1,), (8,)]
        cur.fetchall.return_value = []
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cur
        with patch.object(eval_db, "cursor", return_value=cursor_context):
            eval_db.metric_rows(7, 8, None)
            self.assertNotIn("IS NULL", cur.execute.call_args_list[-1].args[0])
            eval_db.latest_run_id(7, None)
            self.assertNotIn("IS NULL", cur.execute.call_args_list[-1].args[0])

        cur.reset_mock()
        cur.fetchone.side_effect = [(1,), (8,)]
        with patch.object(eval_db, "cursor", return_value=cursor_context):
            eval_db.metric_rows(7, 8, "chat")
            self.assertEqual((8, "chat"), cur.execute.call_args_list[-1].args[1])
            eval_db.latest_run_id(7, "chat")
            self.assertEqual((7, "chat"), cur.execute.call_args_list[-1].args[1])


if __name__ == "__main__":
    unittest.main()
