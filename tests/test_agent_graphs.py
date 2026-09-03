"""Focused regression tests for the LangGraph agent routing."""

import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from langgraph.checkpoint.memory import InMemorySaver

import config
from agents.conversation import api as chat_api
from agents.conversation import graph as chat_loop
from agents.conversation.nodes import approve as chat_approve
from agents.conversation.nodes import handoff as chat_handoff
from agents.conversation.nodes import reason as chat_reason
from agents.conversation.nodes import act as chat_act
from agents.conversation.state import initial_state as chat_initial_state
from agents.enrich import graph as enrich_loop
from agents.enrich.nodes import approval as enrich_approval
from agents.enrich.nodes import model as enrich_model
from agents.enrich.state import Ctx as EnrichCtx
from agents.enrich.state import context_to_dict as enrich_context_data
from agents.enrich.state import initial_state as enrich_initial_state
from tools import enrich as enrich_tools
from tools.enrich import add_note_tags, create_note, list_paths
from agents.runtime.execute_tool import execute_tool as execute_enrich_tool


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
        self.assertIsNotNone(chat_loop.CHAT_GRAPH.checkpointer)
        self.assertIsNotNone(enrich_loop.ENRICH_GRAPH.checkpointer)
        self.assertEqual(
            {"reason", "act", "handoff", "approve"},
            set(chat_loop.CHAT_GRAPH.get_graph().nodes) - {"__start__", "__end__"},
        )
        self.assertEqual(
            {"model", "read_tool", "metadata_context", "metadata_model",
             "metadata_validation", "reminder_model", "reminder_validation",
             "link_context", "pending_write", "approval", "final"},
            set(enrich_loop.ENRICH_GRAPH.get_graph().nodes) - {"__start__", "__end__"},
        )

    def test_chat_routes_read_tool_back_to_model(self):
        replies = [
            completion(tool_name="get_note", arguments='{"note_id": 4}'),
            completion(content="The answer."),
        ]
        with patch.object(chat_reason, "_complete", side_effect=replies), \
                patch.object(chat_act, "execute_tool", return_value='{"id": 4}') as tool:
            result = chat_api.evaluate_turn(
                7, [{"role": "user", "content": "Read it"}], "now", "tz", "en")

        self.assertEqual("answer", result["status"])
        self.assertEqual("The answer.", result["reply"])
        tool.assert_called_once()
        self.assertEqual("tool", result["messages"][-2]["role"])

    def test_chat_reason_provider_error_returns_answer(self):
        with patch.object(chat_reason, "_complete",
                          side_effect=chat_reason.model_gateway.ModelGatewayError(
                              "model_rate_limited", "429 Too Many Requests")):
            result = chat_api.evaluate_turn(
                7, [{"role": "user", "content": "Please analyze my notes"}],
                "now", "tz", "en")

        self.assertEqual("answer", result["status"])
        self.assertIn("try again", result["reply"])
        self.assertIn("model_error", result["trace"])

    def test_detect_reminder_tool_flags_intent_and_time(self):
        from tools.conversation import detect_reminder

        yes = detect_reminder.invoke(
            {}, {"text": "Remind me tomorrow to call Ivan"}).data
        self.assertTrue(yes["is_reminder"])
        self.assertTrue(yes["intent"])
        self.assertTrue(yes["has_time_hint"])

        no = detect_reminder.invoke(
            {}, {"text": "What did I note about the pool?"}).data
        self.assertFalse(no["is_reminder"])

    def test_chat_handoff_pauses_and_resume_executes_after_approval(self):
        action = {"name": "create_note", "args": {"text": "Idea"},
                  "summary": "Create a note: “Idea”."}
        graph = chat_loop.build_graph(InMemorySaver())
        graph_config = {"configurable": {"thread_id": "chat:handoff"}}
        ctx = context()
        with patch.object(chat_reason, "_complete", return_value=completion(
                tool_name="perform_action", arguments='{"instruction": "save Idea"}')), \
                patch.object(chat_handoff.registry.get("enrich"), "plan_action",
                             return_value=action):
            paused = chat_loop.invoke(
                graph, graph_config,
                chat_initial_state(ctx, [{"role": "user", "content": "Save Idea"}]))

        self.assertEqual("confirm", paused["status"])
        self.assertEqual(action, paused["action"])
        self.assertIn("action_id", paused["pending"])

        with patch.object(chat_approve.execution_ledger, "execute_once",
                          side_effect=lambda *args: args[-1]()), \
                patch.object(chat_approve.registry.get("enrich"), "execute_action",
                             return_value='{"note_id": 9}'), \
                patch.object(chat_reason, "_complete", return_value=completion(content="Created.")):
            resumed = chat_loop.resume(graph, graph_config, True)

        self.assertEqual("answer", resumed["status"])
        self.assertEqual("Created.", resumed["reply"])
        self.assertIsNone(resumed["pending"])

    def test_chat_handoff_without_action_returns_to_model(self):
        graph = chat_loop.build_graph(InMemorySaver())
        graph_config = {"configurable": {"thread_id": "chat:no-action"}}
        replies = [
            completion(tool_name="perform_action",
                       arguments='{"instruction": "add a tag to that note"}'),
            completion(content="Which note should I update?"),
        ]
        with patch.object(chat_reason, "_complete", side_effect=replies), \
                patch.object(chat_handoff.registry.get("enrich"), "plan_action",
                             return_value=None):
            result = chat_loop.invoke(
                graph, graph_config,
                chat_initial_state(
                    context(),
                    [{"role": "user", "content": "Add a tag to that note"}]))

        self.assertEqual("answer", result["status"])
        self.assertEqual("Which note should I update?", result["reply"])
        self.assertIsNone(result.get("pending"))

    def test_enrich_write_pauses_and_decline_does_not_execute(self):
        graph = enrich_loop.build_graph(InMemorySaver())
        graph_config = {"configurable": {"thread_id": "enrich:decline"}}
        with patch.object(enrich_model, "complete", return_value=completion(
                tool_name="create_note", arguments='{"text": "Call tomorrow"}')):
            paused = enrich_loop.invoke(
                graph, graph_config,
                enrich_initial_state(
                    context(), [{"role": "user", "content": "Save this"}]))

        self.assertEqual("confirm", paused["status"])
        self.assertEqual("create_note", paused["action"]["name"])

        with patch.object(enrich_approval, "execute_tool") as tool, \
                patch.object(enrich_model, "complete",
                             return_value=completion(content="Cancelled.")):
            resumed = enrich_loop.resume(graph, graph_config, approve=False)

        tool.assert_not_called()
        self.assertEqual("Cancelled.", resumed["reply"])

    def test_enrich_create_note_proposal_is_atomic_before_confirmation(self):
        graph = enrich_loop.build_graph(InMemorySaver())
        graph_config = {"configurable": {"thread_id": "enrich:atomic-note"}}
        verbose = (
            "Atomic idea one. Useful supporting detail. Final relevant nuance. "
            "This fourth sentence is expansion that should not be part of the "
            "atomic note proposal."
        )
        with patch.object(config, "ATOMIC_NOTE_MAX_SENTENCES", 3), \
                patch.object(config, "ATOMIC_NOTE_MAX_CHARS", 700), \
                patch.object(enrich_model, "complete", return_value=completion(
                    tool_name="create_note",
                    arguments=json.dumps({"text": verbose}))):
            paused = enrich_loop.invoke(
                graph, graph_config,
                enrich_initial_state(
                    context(), [{"role": "user", "content": "Save this"}]))

        text = paused["action"]["args"]["text"]
        self.assertEqual(
            "Atomic idea one. Useful supporting detail. Final relevant nuance.",
            text,
        )
        self.assertEqual(text, paused["pending"]["args"]["text"])

    def test_enrich_approval_runs_through_idempotency_ledger(self):
        graph = enrich_loop.build_graph(InMemorySaver())
        graph_config = {"configurable": {"thread_id": "enrich:approve"}}
        with patch.object(enrich_model, "complete", return_value=completion(
                tool_name="create_note", arguments='{"text": "Call tomorrow"}')):
            paused = enrich_loop.invoke(
                graph, graph_config,
                enrich_initial_state(
                    context(), [{"role": "user", "content": "Save this"}]))

        self.assertIn("action_id", paused["pending"])
        with patch.object(enrich_approval.execution_ledger, "execute_once",
                          return_value='{"note_id": 9}') as execute_once, \
                patch.object(enrich_approval, "execute_tool") as tool, \
                patch.object(enrich_model, "complete",
                             return_value=completion(content="Created.")):
            resumed = enrich_loop.resume(graph, graph_config, approve=True)

        self.assertEqual("Created.", resumed["reply"])
        execute_once.assert_called_once()
        tool.assert_not_called()  # callback is passed but the mocked ledger does not run it

    def test_chat_routes_reminder_handoff_and_resumes_same_agent(self):
        action = {"name": "create_reminder",
                  "args": {"text": "Call tomorrow", "remind_at": "2026-09-01T09:00:00+03:00"},
                  "summary": "Create a reminder."}
        graph = chat_loop.build_graph(InMemorySaver())
        graph_config = {"configurable": {"thread_id": "chat:reminder"}}
        ctx = context()
        with patch.object(chat_reason, "_complete", return_value=completion(
                tool_name="set_reminder",
                arguments='{"instruction": "Call tomorrow"}')), \
                patch.object(chat_handoff.registry.get("enrich"), "plan_action",
                             return_value=action):
            paused = chat_loop.invoke(
                graph, graph_config,
                chat_initial_state(ctx, [{"role": "user", "content": "Remind me"}]))

        self.assertEqual("confirm", paused["status"])
        self.assertEqual("enrich", paused["pending"]["agent"])

        with patch.object(chat_approve.execution_ledger, "execute_once",
                          side_effect=lambda *args: args[-1]()), \
                patch.object(chat_approve.registry.get("enrich"), "execute_action",
                          return_value='{"reminder_id": 3}') as reminder_execute, \
                patch.object(chat_reason, "_complete", return_value=completion(content="Scheduled.")):
            resumed = chat_loop.resume(graph, graph_config, True)

        reminder_execute.assert_called_once()
        self.assertEqual("Scheduled.", resumed["reply"])

    def test_main_enrich_graph_resolves_reminder_before_confirmation(self):
        graph = enrich_loop.build_graph(InMemorySaver())
        graph_config = {"configurable": {"thread_id": "enrich:reminder"}}
        raw = '{"is_reminder": true, "remind_at": "2026-09-01T09:00:00+00:00"}'
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=Mock(return_value=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=raw))])))))

        with patch.object(enrich_model, "complete", return_value=completion(
                tool_name="create_reminder",
                arguments='{"text": "Call tomorrow"}')), \
                patch.object(enrich_loop.reminder.model_gateway, "chat_completion",
                             return_value=client.chat.completions.create()):
            paused = enrich_loop.invoke(
                graph, graph_config,
                enrich_initial_state(
                    SimpleNamespace(
                        user_id=7, now=datetime(2026, 8, 31, 10, 0,
                                                tzinfo=timezone.utc),
                        tz=timezone.utc, locale="en"),
                    [{"role": "user", "content": "Remind me to call tomorrow"}]))

        self.assertEqual("confirm", paused["status"])
        self.assertEqual("create_reminder", paused["action"]["name"])
        self.assertEqual("2026-09-01T09:00:00+00:00",
                         paused["action"]["args"]["remind_at"])
        self.assertEqual(
            ["reminder_model", "reminder_validation"],
            [event["node"] for event in paused["reminder_trace"]])

    def test_reminder_graph_resolves_time_before_confirmation(self):
        now = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
        remind_at = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
        contract = {"instruction": "Call tomorrow", "resolved_entities": {}}
        with patch.object(enrich_loop.reminder, "extract_time", return_value={
            "reminder_raw": {"is_reminder": True,
                             "remind_at": remind_at.isoformat()},
            "reminder_trace": [{"node": "reminder_model", "status": "ok"}],
        }):
            graph = enrich_loop.build_reminder_plan_graph()
            action = graph.invoke({
                "contract": contract, "now": now, "action": None,
                "reminder_trace": [],
            })["action"]

        self.assertEqual("create_reminder", action["name"])
        self.assertEqual(remind_at.isoformat(), action["args"]["remind_at"])

    def test_enrich_owns_reminder_tool(self):
        self.assertIn("create_reminder", enrich_tools.WRITE_TOOLS)
        names = {spec["function"]["name"] for spec in enrich_tools.TOOL_SPECS}
        self.assertIn("create_reminder", names)

    def test_enrich_add_note_tags_merges_existing_tags(self):
        with patch.object(add_note_tags.db, "get_note_for_user",
                          return_value={"id": 4, "tags": ["old", "keep"]}), \
                patch.object(add_note_tags.db, "set_tags") as set_tags:
            result = execute_enrich_tool(
                enrich_tools.TOOLS,
                enrich_context_data(EnrichCtx(7, "now", "tz", "en")),
                "add_note_tags",
                {"note_id": 4, "tags": ["New", "old", ""]},
                "enrich",
            ).data

        self.assertEqual({"ok": True, "note_id": 4,
                          "tags": ["old", "keep", "new"]}, result)
        set_tags.assert_called_once_with(4, ["old", "keep", "new"])

    def test_enrich_tools_validate_context_and_args_values(self):
        with patch.object(add_note_tags.db, "get_note_for_user") as get_note, \
                patch.object(create_note.db, "save_note") as save_note, \
                patch.object(list_paths.db, "list_paths") as paths:
            self.assertEqual(
                "Error: context is missing required values: user_id.",
                add_note_tags.invoke({}, {"note_id": 4, "tags": ["new"]}).data["error"],
            )
            self.assertEqual(
                "Error: args is missing required values: text.",
                create_note.invoke({"user_id": 7}, {"text": ""}).data["error"],
            )
            self.assertEqual(
                "Error: args must be an object.",
                list_paths.invoke({"user_id": 7}, None).data["error"],
            )

        get_note.assert_not_called()
        save_note.assert_not_called()
        paths.assert_not_called()

    def test_chat_handoff_action_is_planned_by_enrich_subgraph(self):
        create = Mock(return_value=completion(
            tool_name="create_note", arguments='{"text": "Graph idea"}'))
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        specs = [{"type": "function", "function": {"name": "create_note"}}]

        with patch.object(enrich_model.model_gateway, "chat_completion",
                          side_effect=client.chat.completions.create):
            result = enrich_loop.ACTION_PLAN_GRAPH.invoke({
                "messages": [{"role": "user", "content": "Save Graph idea"}],
                "context": enrich_context_data(context()), "tool_specs": specs,
                "steps": 0, "tool_call": None, "action": None,
            })
            action = result.get("action")

        self.assertEqual("create_note", action["name"])
        self.assertEqual({"text": "Graph idea"}, action["args"])
        create.assert_called_once()

    def test_enrich_planning_provider_error_returns_no_action(self):
        with patch.object(enrich_model.model_gateway, "chat_completion",
                          side_effect=enrich_model.model_gateway.ModelGatewayError(
                              "model_rate_limited", "429 Too Many Requests")):
            result = enrich_loop.ACTION_PLAN_GRAPH.invoke({
                "messages": [{"role": "user", "content": "Save Graph idea"}],
                "context": enrich_context_data(context()),
                "tool_specs": enrich_tools.TOOL_SPECS,
                "steps": 0, "tool_call": None, "action": None,
            })

        self.assertIsNone(result.get("action"))
        self.assertIn("model_error", result)

    def test_step_budget_routes_to_tool_free_final_node(self):
        replies = [
            completion(tool_name="list_paths"),
            completion(content="I couldn't complete the lookup."),
        ]
        with patch.object(chat_loop.config, "AGENT_MAX_STEPS", 1), \
                patch.object(chat_reason, "_complete", side_effect=replies), \
                patch.object(chat_act, "execute_tool", return_value="[]"):
            result = chat_api.evaluate_turn(
                7, [{"role": "user", "content": "Paths"}], "now", "tz", "en")

        self.assertEqual("I couldn't complete the lookup.", result["reply"])


if __name__ == "__main__":
    unittest.main()
