"""The reminder agent's side of the loop contract.

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

    # The planning graph is LangGraph; the agent only needs the action it
    # returns. Stubbing the graph rather than a planning module is what the
    # merge changed: planning now lives in `agent.py` itself, so the seam the
    # test stands on is the graph, not a second module.
    graph = types.ModuleType("agents.reminder.graph")
    graph.PLAN_GRAPH = types.SimpleNamespace(invoke=None)

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

    sys.modules["agents.reminder.graph"] = graph
    sys.modules["tools.reminder"] = tools

    return planned, executed


PLANNED, EXECUTED = _install_stubs()
PLAN_GRAPH = sys.modules["agents.reminder.graph"].PLAN_GRAPH


def _plan_from_planned(state):
    """The stub graph's default: return whatever the test planned."""
    return {"action": PLANNED["action"], "events": []}


def _record_plan_state(seen):
    """A stub graph that also captures the state it was invoked with.

    Tests that install this restore the default in `tearDown` — leaving it
    bound would hand every later test a hard-coded action, which is exactly
    the ordering bug this indirection removes."""
    def invoke(state):
        seen.update(state)

        return {"action": PLANNED["action"], "events": []}

    return invoke


PLAN_GRAPH.invoke = _plan_from_planned

from agents.contracts import AgentRequest, Ref, ToolResult  # noqa: E402
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
        PLAN_GRAPH.invoke = _record_plan_state(seen)
        self.addCleanup(setattr, PLAN_GRAPH, "invoke", _plan_from_planned)

        agent.start(_request(referenced_note_ids=[4, 9], conversation_summary="about teeth"))

        plan_request = seen["contract"]
        self.assertEqual([4, 9], plan_request["referenced_note_ids"])
        self.assertEqual("about teeth", plan_request["conversation_summary"])
        self.assertEqual("Europe/Kyiv", plan_request["timezone"])
        self.assertEqual("uk", plan_request["locale"], "the clock comes from context")

    def test_no_resolvable_time_finishes_without_asking(self):
        PLANNED["action"] = None

        result = agent.start(_request("something vague"))

        self.assertEqual("done", result.status)
        self.assertIsNone(result.ask)
        self.assertEqual((), result.produced)


class PlanRequestTests(unittest.TestCase):
    """The envelope -> planning contract mapping, which the merge made this
    agent's own. It used to be built twice — once from the request, then
    re-validated by the planning module — so nothing covered the coercion."""

    def setUp(self):
        PLANNED["action"] = ACTION
        EXECUTED["result"] = None
        self.seen = {}
        PLAN_GRAPH.invoke = _record_plan_state(self.seen)
        self.addCleanup(setattr, PLAN_GRAPH, "invoke", _plan_from_planned)

    def _plan_request(self, **references):
        agent.start(_request(**references))

        return self.seen["contract"]

    def test_note_ids_arrive_as_ints_whatever_the_client_sent(self):
        plan_request = self._plan_request(referenced_note_ids=["4", 9])

        self.assertEqual([4, 9], plan_request["referenced_note_ids"])

    def test_an_unparseable_note_id_is_dropped_not_fatal(self):
        """One bad reference must not lose the reminder."""
        plan_request = self._plan_request(referenced_note_ids=[4, "nope", None, 9])

        self.assertEqual([4, 9], plan_request["referenced_note_ids"])

    def test_missing_references_become_empty_rather_than_none(self):
        """The planner reads these unconditionally; `None` would raise inside
        the graph instead of here."""
        plan_request = self._plan_request()

        self.assertEqual([], plan_request["referenced_note_ids"])
        self.assertEqual("", plan_request["conversation_summary"])
        self.assertEqual([], plan_request["citations"])
        self.assertEqual({"referenced_notes": []}, plan_request["resolved_entities"])

    def test_referenced_notes_are_hydrated_for_the_planner(self):
        """Without this the planner sees an id, not a note, and cannot resolve
        "that note"."""
        EXECUTED["result"] = ToolResult({"id": 4, "title": "Dentist"})

        plan_request = self._plan_request(referenced_note_ids=[4])

        self.assertEqual(
            [{"id": 4, "title": "Dentist", "note_id": 4}],
            plan_request["resolved_entities"]["referenced_notes"])

    def test_a_note_that_cannot_be_read_is_skipped(self):
        EXECUTED["result"] = ToolResult({"error": "Error: note not found."})

        plan_request = self._plan_request(referenced_note_ids=[4])

        self.assertEqual([], plan_request["resolved_entities"]["referenced_notes"])


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
        self.assertEqual((), agent.SPEC.may_read,
                         "it never calls read_state, so it grants itself nothing")
        self.assertTrue(agent.SPEC.description.strip())
        self.assertIsNotNone(agent.SPEC.resume)


if __name__ == "__main__":
    unittest.main()
