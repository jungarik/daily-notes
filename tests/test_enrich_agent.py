"""The enrich agent's side of the broker contract.

The planning graph and the tool registry are stubbed, so this exercises the
adapter — the five write shapes, the select action's user choice, the refs it
reports — without LangGraph, a model, or a database.
"""

import json
import sys
import types
import unittest


def _install_stubs():
    """Stand in for the modules `agents.enrich.agent` imports at module level."""
    planned = {"action": None}
    executed = {"result": None, "calls": []}

    handoff = types.ModuleType("agents.enrich.handoff_api")
    handoff.plan_action = lambda user_id, request, now, tz, locale: planned["action"]
    handoff.execute_action = lambda user_id, action, now, tz, locale: ""

    execute = types.ModuleType("agents.runtime.execute_tool")

    def execute_tool(registry, context, name, args, owner="tool"):
        executed["calls"].append({"context": context, "name": name, "args": args})

        return executed["result"]

    execute.execute_tool = execute_tool
    execute.execute_allowed_tool = lambda *args, **kwargs: None

    # The tool package reaches psycopg at import time; the agent only needs the
    # registry it exposes.
    tools = types.ModuleType("tools.enrich")
    tools.TOOLS = {name: (lambda context, args: None) for name in (
        "create_note", "set_note_path", "enrich_note", "add_note_tags", "link_notes")}
    tools.CONTEXT_TOOLS = set()
    tools.TOOL_SPECS = []
    tools.WRITE_TOOLS = set(tools.TOOLS)

    sys.modules["agents.enrich.handoff_api"] = handoff
    sys.modules["agents.runtime.execute_tool"] = execute
    sys.modules["tools.enrich"] = tools

    return planned, executed


PLANNED, EXECUTED = _install_stubs()

from agents.broker.contracts import AgentRequest, Ref  # noqa: E402
from agents.contracts import ToolResult  # noqa: E402
from agents.enrich import agent  # noqa: E402

CONTEXT = {
    "user_id": 7,
    "now": "2026-09-23T09:00:00",
    "tz": "Europe/Kyiv",
    "locale": "uk",
}


def _request(message="file that under projects", **references):
    return AgentRequest(
        request_id="r1",
        correlation_id="c1",
        causation_id=None,
        agent="enrich",
        message=message,
        context=CONTEXT,
        references=dict(references),
        hops_left=4)


def _action(name, **args):
    return {"name": name, "args": args, "summary": f"{name} summary"}


class StartTests(unittest.TestCase):
    def tearDown(self):
        PLANNED["action"] = None

    def test_a_planned_write_pauses_for_confirmation(self):
        PLANNED["action"] = _action("create_note", text="a thought")

        result = agent.start(_request())

        self.assertEqual("needs_input", result.status)
        self.assertEqual("confirm", result.ask["kind"])
        self.assertEqual((), result.produced, "planning makes nothing")

    def test_link_notes_asks_for_a_selection_not_a_yes_or_no(self):
        """`link_notes` is the one action where the user chooses rather than
        approves, so the ask has to say so or the client renders a bare
        confirm."""
        PLANNED["action"] = _action("link_notes", note_id=1, linked_note_ids=[2, 3])

        result = agent.start(_request())

        self.assertEqual("select", result.ask["kind"])

    def test_nothing_plannable_finishes_without_asking(self):
        PLANNED["action"] = None

        result = agent.start(_request("something vague"))

        self.assertEqual("done", result.status)
        self.assertIsNone(result.ask)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        EXECUTED["calls"].clear()
        EXECUTED["result"] = ToolResult({"ok": True, "note_id": 1, "linked_note_ids": [9]})

    def test_the_users_choice_replaces_the_proposed_links(self):
        token = json.dumps(_action("link_notes", note_id=1, linked_note_ids=[2, 3, 4]))

        agent.resume(token, {"approve": True, "selection": [9]}, CONTEXT)

        self.assertEqual([9], EXECUTED["calls"][0]["args"]["linked_note_ids"])

    def test_unparseable_ids_are_dropped_not_fatal(self):
        token = json.dumps(_action("link_notes", note_id=1, linked_note_ids=[2]))

        agent.resume(token, {"approve": True, "selection": ["9", 9, "nope", 10]}, CONTEXT)

        self.assertEqual([9, 10], EXECUTED["calls"][0]["args"]["linked_note_ids"])

    def test_a_selection_is_ignored_for_a_plain_confirm_action(self):
        EXECUTED["result"] = ToolResult({"note_id": 5})
        token = json.dumps(_action("create_note", text="a thought"))

        agent.resume(token, {"approve": True, "selection": [1, 2]}, CONTEXT)

        self.assertNotIn("linked_note_ids", EXECUTED["calls"][0]["args"])

    def test_no_selection_leaves_the_planned_links_alone(self):
        token = json.dumps(_action("link_notes", note_id=1, linked_note_ids=[2, 3]))

        agent.resume(token, {"approve": True}, CONTEXT)

        self.assertEqual([2, 3], EXECUTED["calls"][0]["args"]["linked_note_ids"])


class RefTests(unittest.TestCase):
    """Five write tools, five result shapes — the refs have to survive all of
    them or the history lies about what the turn did."""

    def setUp(self):
        EXECUTED["calls"].clear()

    def _resume(self, action, data):
        EXECUTED["result"] = ToolResult(data)

        return agent.resume(json.dumps(action), {"approve": True}, CONTEXT)

    def test_create_note_reports_the_new_note(self):
        result = self._resume(_action("create_note", text="x"), {"note_id": 12})

        self.assertEqual((Ref("note", "12"),), result.produced)

    def test_set_note_path_reports_the_note_it_moved(self):
        """`set_note_path` returns only `{ok, path}`, so the note has to come
        from the action's args or the hop looks like it did nothing."""
        result = self._resume(
            _action("set_note_path", note_id=8, path="Projects/x"),
            {"ok": True, "path": "Projects/x"})

        self.assertEqual((Ref("note", "8"),), result.produced)

    def test_add_note_tags_reports_the_note_not_the_tags(self):
        result = self._resume(
            _action("add_note_tags", note_id=8, tags=["a"]),
            {"ok": True, "note_id": 8, "tags": ["a", "b"]})

        self.assertEqual((Ref("note", "8"),), result.produced)

    def test_link_notes_reports_the_note_and_one_ref_per_link(self):
        result = self._resume(
            _action("link_notes", note_id=1, linked_note_ids=[2, 3]),
            {"ok": True, "note_id": 1, "linked_note_ids": [2, 3]})

        self.assertEqual(
            (Ref("note", "1"), Ref("link", "1-2"), Ref("link", "1-3")),
            result.produced)

    def test_enrich_note_reports_the_note_from_the_args(self):
        result = self._resume(
            _action("enrich_note", note_id=4),
            {"title": "A title", "path": "Notes/x", "tags": []})

        self.assertEqual((Ref("note", "4"),), result.produced)


class FailureTests(unittest.TestCase):
    def setUp(self):
        EXECUTED["calls"].clear()

    def test_a_tool_error_is_a_failure_not_an_empty_success(self):
        EXECUTED["result"] = ToolResult({"error": "Error: note not found."})

        result = agent.resume(
            json.dumps(_action("set_note_path", note_id=8)), {"approve": True}, CONTEXT)

        self.assertEqual("failed", result.status)
        self.assertEqual((), result.produced)

    def test_a_degraded_string_result_is_also_a_failure(self):
        EXECUTED["result"] = "Error running create_note: boom"

        result = agent.resume(
            json.dumps(_action("create_note", text="x")), {"approve": True}, CONTEXT)

        self.assertEqual("failed", result.status)
        self.assertIn("boom", result.error)


class SpecTests(unittest.TestCase):
    def test_the_spec_declares_its_entry_tool_and_read_scope(self):
        self.assertEqual("enrich", agent.SPEC.name)
        self.assertEqual(("perform_action",), agent.SPEC.entry_tools)
        self.assertEqual(("conversation",), agent.SPEC.may_read)
        self.assertTrue(agent.SPEC.description.strip())
        self.assertIsNotNone(agent.SPEC.resume)

    def test_it_does_not_claim_the_reminder_entry_tool(self):
        """Both agents register into one registry; a shared entry tool would
        raise at import, but this says which one is enrich's."""
        self.assertNotIn("set_reminder", agent.SPEC.entry_tools)


if __name__ == "__main__":
    unittest.main()
