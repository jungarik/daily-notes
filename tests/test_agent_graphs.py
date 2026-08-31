"""Focused regression tests for the LangGraph agent routing."""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agents.chat import loop as chat_loop
from agents.enrich import loop as enrich_loop
from agents.enrich import tools as enrich_tools
from agents.reminder import loop as reminder_loop


def completion(content=None, tool_name=None, arguments="{}", call_id="call-1"):
    calls = []
    if tool_name:
        calls.append(SimpleNamespace(
            id=call_id,
            function=SimpleNamespace(name=tool_name, arguments=arguments),
        ))
    message = SimpleNamespace(content=content, tool_calls=calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def context():
    return SimpleNamespace(user_id=7, now="now", tz="tz", locale="en")


class AgentGraphTests(unittest.TestCase):
    def test_graphs_expose_named_workflow_nodes(self):
        self.assertEqual(
            {"model", "read_tool", "enrich_agent", "reminder_agent",
             "resume_action", "final"},
            set(chat_loop.CHAT_GRAPH.get_graph().nodes) - {"__start__", "__end__"},
        )
        self.assertEqual(
            {"model", "read_tool", "pending_write", "resume_write", "final"},
            set(enrich_loop.ENRICH_GRAPH.get_graph().nodes) - {"__start__", "__end__"},
        )
        self.assertEqual(
            {"parse_time", "prepare_action"},
            set(reminder_loop.REMINDER_GRAPH.get_graph().nodes) - {"__start__", "__end__"},
        )

    def test_chat_routes_read_tool_back_to_model(self):
        replies = [
            completion(tool_name="get_note", arguments='{"note_id": 4}'),
            completion(content="The answer."),
        ]
        with patch.object(chat_loop, "_complete", side_effect=replies), \
                patch.object(chat_loop, "execute_tool", return_value='{"id": 4}') as tool:
            result = chat_loop.run_loop(context(), [{"role": "user", "content": "Read it"}])

        self.assertEqual("answer", result["status"])
        self.assertEqual("The answer.", result["reply"])
        tool.assert_called_once()
        self.assertEqual("tool", result["messages"][-2]["role"])

    def test_chat_handoff_pauses_and_resume_executes_after_approval(self):
        action = {"name": "create_note", "args": {"text": "Idea"},
                  "summary": "Create a note: “Idea”."}
        with patch.object(chat_loop, "_complete", return_value=completion(
                tool_name="perform_action", arguments='{"instruction": "save Idea"}')), \
                patch.object(chat_loop.enrich_service, "plan_action", return_value=action):
            paused = chat_loop.run_loop(context(), [{"role": "user", "content": "Save Idea"}])

        self.assertEqual("confirm", paused["status"])
        self.assertEqual(action, paused["action"])
        self.assertIn("action_id", paused["pending"])

        with patch.object(chat_loop.action_execution, "execute_once",
                          side_effect=lambda *args: args[-1]()), \
                patch.object(chat_loop.enrich_service, "execute_action",
                             return_value='{"note_id": 9}'), \
                patch.object(chat_loop, "_complete", return_value=completion(content="Created.")):
            resumed = chat_loop.resume_action(
                context(), paused["messages"], paused["pending"], approve=True)

        self.assertEqual("answer", resumed["status"])
        self.assertEqual("Created.", resumed["reply"])
        self.assertIsNone(resumed["pending"])

    def test_enrich_write_pauses_and_decline_does_not_execute(self):
        with patch.object(enrich_loop, "_complete", return_value=completion(
                tool_name="create_note", arguments='{"text": "Call tomorrow"}')):
            paused = enrich_loop.run_loop(
                context(), [{"role": "user", "content": "Save this"}])

        self.assertEqual("confirm", paused["status"])
        self.assertEqual("create_note", paused["action"]["name"])

        with patch.object(enrich_loop, "execute_tool") as tool, \
                patch.object(enrich_loop, "_complete", return_value=completion(content="Cancelled.")):
            resumed = enrich_loop.resume_write(
                context(), paused["messages"], paused["pending"], approve=False)

        tool.assert_not_called()
        self.assertEqual("Cancelled.", resumed["reply"])

    def test_enrich_approval_runs_through_idempotency_ledger(self):
        with patch.object(enrich_loop, "_complete", return_value=completion(
                tool_name="create_note", arguments='{"text": "Call tomorrow"}')):
            paused = enrich_loop.run_loop(
                context(), [{"role": "user", "content": "Save this"}])

        self.assertIn("action_id", paused["pending"])
        with patch.object(enrich_loop.action_execution, "execute_once",
                          return_value='{"note_id": 9}') as execute_once, \
                patch.object(enrich_loop, "execute_tool") as tool, \
                patch.object(enrich_loop, "_complete",
                             return_value=completion(content="Created.")):
            resumed = enrich_loop.resume_write(
                context(), paused["messages"], paused["pending"], approve=True)

        self.assertEqual("Created.", resumed["reply"])
        execute_once.assert_called_once()
        tool.assert_not_called()  # callback is passed but the mocked ledger does not run it

    def test_chat_routes_reminder_handoff_and_resumes_same_agent(self):
        action = {"name": "create_reminder",
                  "args": {"text": "Call tomorrow", "remind_at": "2026-09-01T09:00:00+03:00"},
                  "summary": "Create a reminder."}
        with patch.object(chat_loop, "_complete", return_value=completion(
                tool_name="set_reminder",
                arguments='{"instruction": "Call tomorrow"}')), \
                patch.object(chat_loop.reminder_service, "plan_action", return_value=action):
            paused = chat_loop.run_loop(context(), [{"role": "user", "content": "Remind me"}])

        self.assertEqual("confirm", paused["status"])
        self.assertEqual("reminder", paused["pending"]["agent"])

        with patch.object(chat_loop.action_execution, "execute_once",
                          side_effect=lambda *args: args[-1]()), \
                patch.object(chat_loop.reminder_service, "execute_action",
                          return_value='{"reminder_id": 3}') as reminder_execute, \
                patch.object(chat_loop.enrich_service, "execute_action") as enrich_execute, \
                patch.object(chat_loop, "_complete", return_value=completion(content="Scheduled.")):
            resumed = chat_loop.resume_action(
                context(), paused["messages"], paused["pending"], approve=True)

        reminder_execute.assert_called_once()
        enrich_execute.assert_not_called()
        self.assertEqual("Scheduled.", resumed["reply"])

    def test_reminder_graph_resolves_time_before_confirmation(self):
        now = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
        remind_at = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
        with patch.object(reminder_loop.domain, "extract_time", return_value=remind_at):
            action = reminder_loop.plan("Call tomorrow", now)

        self.assertEqual("create_reminder", action["name"])
        self.assertEqual(remind_at.isoformat(), action["args"]["remind_at"])

    def test_enrich_no_longer_owns_reminder_tool(self):
        self.assertNotIn("create_reminder", enrich_tools.WRITE_TOOLS)
        names = {spec["function"]["name"] for spec in enrich_tools.TOOL_SPECS}
        self.assertNotIn("create_reminder", names)

    def test_chat_handoff_action_is_planned_by_enrich_subgraph(self):
        create = Mock(return_value=completion(
            tool_name="create_note", arguments='{"text": "Graph idea"}'))
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        specs = [{"type": "function", "function": {"name": "create_note"}}]

        with patch.object(enrich_loop.openai_client, "get_client", return_value=client):
            action = enrich_loop.plan_action(
                [{"role": "user", "content": "Save Graph idea"}], specs)

        self.assertEqual("create_note", action["name"])
        self.assertEqual({"text": "Graph idea"}, action["args"])
        create.assert_called_once()

    def test_step_budget_routes_to_tool_free_final_node(self):
        replies = [
            completion(tool_name="list_paths"),
            completion(content="I couldn't complete the lookup."),
        ]
        with patch.object(chat_loop.config, "AGENT_MAX_STEPS", 1), \
                patch.object(chat_loop, "_complete", side_effect=replies), \
                patch.object(chat_loop, "execute_tool", return_value="[]"):
            result = chat_loop.run_loop(context(), [{"role": "user", "content": "Paths"}])

        self.assertEqual("I couldn't complete the lookup.", result["reply"])


if __name__ == "__main__":
    unittest.main()
