"""The reminder agent's side of the broker contract.

The planning graph and the tool registry are stubbed, so this exercises the
adapter — clock restoration, the pause, the refs it reports — without LangGraph,
a model, or a database.
"""

import sys
import types
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo


def _install_stubs():
    """Stand in for the modules `agents.reminder.agent` imports at module level."""
    planned = {"action": None}
    executed = {"result": None, "calls": []}

    handoff = types.ModuleType("agents.reminder.handoff_api")
    handoff.plan_action = lambda user_id, request, now, tz, locale: planned["action"]
    handoff.execute_action = lambda user_id, action, now, tz, locale: ""

    # The tool package reaches psycopg at import time; the agent only needs the
    # registry it exposes. Recording happens in the tool rather than in a stubbed
    # `execute_tool`, so the real runtime adapter still runs — and so this file
    # does not replace a module every other agent in the suite also imports.
    def _record_call(name):
        def invoke(context, args):
            executed["calls"].append({
                "context": context,
                "name": name,
                "args": args,
            })

            return executed["result"]

        return invoke

    tools = types.ModuleType("tools.reminder")
    tools.TOOLS = {
        name: _record_call(name)
        for name in ("create_reminder", "get_note_context")
    }
    tools.CONTEXT_TOOLS = {"get_note_context"}
    tools.TOOL_SPECS = []
    tools.WRITE_TOOLS = {"create_reminder"}

    sys.modules["agents.reminder.handoff_api"] = handoff
    sys.modules["tools.reminder"] = tools

    return planned, executed


PLANNED, EXECUTED = _install_stubs()

from agents.broker.contracts import AgentRequest, Ref  # noqa: E402
from agents.contracts import ToolResult  # noqa: E402
from agents.reminder import agent  # noqa: E402

CONTEXT = {
    "user_id": 7,
    "now": "2026-09-18T09:00:00",
    "tz": "Europe/Kyiv",
    "locale": "uk",
}

ACTION = {
    "name": "create_reminder",
    "args": {"text": "call the dentist", "remind_at": "2026-09-19T10:00:00"},
    "summary": "Remind you to call the dentist tomorrow at 10:00",
}


def _request(message="remind me to call the dentist tomorrow", **references):
    return AgentRequest(
        request_id="r1",
        correlation_id="c1",
        causation_id=None,
        agent="reminder",
        message=message,
        context=CONTEXT,
        references=dict(references),
        hops_left=4)


class StartTests(unittest.TestCase):
    def tearDown(self):
        PLANNED["action"] = None

    def test_a_planned_reminder_pauses_for_confirmation(self):
        PLANNED["action"] = ACTION

        result = agent.start(_request())

        self.assertEqual("needs_input", result.status)
        self.assertEqual(ACTION, result.ask["action"])
        self.assertEqual(ACTION["summary"], result.ask["summary"])
        self.assertEqual((), result.produced, "planning makes nothing")

    def test_the_token_carries_what_resume_needs(self):
        PLANNED["action"] = ACTION

        result = agent.start(_request())

        self.assertIsNotNone(result.token)
        self.assertEqual(ACTION, __import__("json").loads(result.token))

    def test_references_feed_the_plan_and_the_clock_comes_from_context(self):
        PLANNED["action"] = ACTION
        seen = {}
        sys.modules["agents.reminder.handoff_api"].plan_action = (
            lambda user_id, request, now, tz, locale: seen.update(
                user_id=user_id, request=request) or ACTION)

        agent.start(_request(referenced_note_ids=[4, 9], conversation_summary="about teeth"))

        self.assertEqual(7, seen["user_id"], "the owner comes from context")
        self.assertEqual([4, 9], seen["request"]["referenced_note_ids"])
        self.assertEqual("about teeth", seen["request"]["conversation_summary"])
        self.assertEqual("Europe/Kyiv", seen["request"]["timezone"])

    def test_no_resolvable_time_finishes_without_asking(self):
        PLANNED["action"] = None

        result = agent.start(_request("something vague"))

        self.assertEqual("done", result.status)
        self.assertIsNone(result.ask)
        self.assertEqual((), result.produced)


class ResumeTests(unittest.TestCase):
    def setUp(self):
        EXECUTED["calls"].clear()
        self.token = __import__("json").dumps(ACTION)

    def test_a_successful_write_reports_both_refs(self):
        EXECUTED["result"] = ToolResult({
            "note_id": 12, "reminder_id": 99, "remind_at": "2026-09-19T10:00:00"})

        result = agent.resume(self.token, {"approve": True}, CONTEXT)

        self.assertEqual("done", result.status)
        self.assertEqual((Ref("reminder", "99"), Ref("note", "12")), result.produced)

    def test_the_clock_is_restored_from_the_envelope(self):
        EXECUTED["result"] = ToolResult({"reminder_id": 1})

        agent.resume(self.token, {"approve": True}, CONTEXT)

        context = EXECUTED["calls"][0]["context"]
        self.assertEqual("Europe/Kyiv", context["tz"])
        self.assertEqual("uk", context["locale"])
        self.assertEqual("2026-09-18T09:00:00", context["now"])

    def test_a_tool_error_is_a_failure_not_an_empty_success(self):
        EXECUTED["result"] = ToolResult({"error": "Error: referenced note not found."})

        result = agent.resume(self.token, {"approve": True}, CONTEXT)

        self.assertEqual("failed", result.status)
        self.assertEqual((), result.produced)

    def test_a_degraded_string_result_is_also_a_failure(self):
        EXECUTED["result"] = "Error running create_reminder: boom"

        result = agent.resume(self.token, {"approve": True}, CONTEXT)

        self.assertEqual("failed", result.status)
        self.assertIn("boom", result.error)


class ClockTests(unittest.TestCase):
    def test_a_missing_timezone_stays_none(self):
        now, tz, locale = agent._restore_clock({"now": "2026-09-18T09:00:00", "tz": None})

        self.assertEqual(datetime(2026, 9, 18, 9, 0), now)
        self.assertIsNone(tz)
        self.assertEqual("en", locale)

    def test_a_named_zone_is_restored_as_a_zone(self):
        _, tz, _ = agent._restore_clock({"now": "2026-09-18T09:00:00", "tz": "Europe/Kyiv"})

        self.assertEqual(ZoneInfo("Europe/Kyiv"), tz)

    def test_an_empty_timezone_string_stays_none(self):
        _, tz, _ = agent._restore_clock({"now": "2026-09-18T09:00:00", "tz": ""})

        self.assertIsNone(tz)

    def test_a_datetime_passes_through_unparsed(self):
        moment = datetime(2026, 9, 18, 9, 0)
        now, _, _ = agent._restore_clock({"now": moment, "tz": None})

        self.assertIs(moment, now)


class SpecTests(unittest.TestCase):
    def test_the_spec_declares_its_entry_tool_and_read_scope(self):
        self.assertEqual("reminder", agent.SPEC.name)
        self.assertEqual(("set_reminder",), agent.SPEC.entry_tools)
        self.assertEqual(("conversation",), agent.SPEC.may_read)
        self.assertTrue(agent.SPEC.description.strip())
        self.assertIsNotNone(agent.SPEC.resume)


if __name__ == "__main__":
    unittest.main()
