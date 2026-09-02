"""Conversational specialist handoff and read-before-write regressions."""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import ANY, Mock, patch

from langgraph.checkpoint.memory import InMemorySaver

from agents.contracts import ToolResult
from agents.conversation import api as chat_service
from agents.conversation import graph as chat_loop
from agents.conversation.nodes import dispatch as chat_dispatch
from agents.conversation.nodes import model as chat_model
from agents.conversation.nodes import read as chat_read
from agents.conversation.state import ConversationContext as ChatCtx, initial_state as chat_initial_state
from agents.enrich import graph as enrich_loop
from agents.enrich.nodes import model as enrich_model
from agents.enrich.nodes import read as enrich_read
from agents.enrich.nodes import write as enrich_write
from agents.enrich.state import Ctx as EnrichCtx
from agents.enrich.state import context_to_dict as enrich_context_data
from agents.enrich import api as enrich_service
from tools import enrich as enrich_tools


def completion(content=None, tool_name=None, arguments="{}", call_id="call-1"):
    calls = []
    if tool_name:
        calls.append(SimpleNamespace(
            id=call_id,
            function=SimpleNamespace(name=tool_name, arguments=arguments),
        ))
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content, tool_calls=calls))])


class HandoffContextTests(unittest.TestCase):
    def test_chat_passes_conversation_citations_and_tool_results(self):
        now = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
        planner = Mock(return_value={
            "name": "set_note_path", "args": {"note_id": 4, "path": "Projects"},
            "summary": "Move note 4",
        })
        replies = [
            completion(tool_name="get_note", arguments='{"note_id": 4}', call_id="read-1"),
            completion(tool_name="perform_action",
                       arguments='{"instruction": "Move that note to Projects"}',
                       call_id="write-1"),
        ]

        def read_tool(_registry, _context, _name, _args, _owner):
            return ToolResult(
                {"id": 4, "title": "Product roadmap", "path": "Areas"},
                citations=[{"note_id": 4, "title": "Product roadmap"}],
            )

        with patch.object(chat_model, "complete", side_effect=replies), \
                patch.object(chat_read, "execute_tool", side_effect=read_tool), \
                patch.object(chat_dispatch.registry.get("enrich"), "plan_action", planner):
            result = chat_service.evaluate_turn(
                7, [{"role": "user", "content": "Open the product roadmap"}],
                now, timezone.utc, "en")

        contract = planner.call_args.args[1]
        self.assertEqual("confirm", result["status"])
        self.assertEqual([4], contract["referenced_note_ids"])
        self.assertEqual("Product roadmap", contract["citations"][0]["title"])
        self.assertIn("Open the product roadmap", contract["conversation_summary"])
        self.assertEqual("get_note",
                         contract["resolved_entities"]["recent_tool_results"][0]["tool"])
        self.assertEqual("UTC", contract["timezone"])

    def test_reference_notes_survive_into_a_later_chat_turn(self):
        now = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
        graph = chat_loop.build_graph(InMemorySaver())
        graph_config = {"configurable": {"thread_id": "chat:references"}}

        def read_tool(_registry, _context, _name, _args, _owner):
            return ToolResult(
                {"id": 4, "title": "Product roadmap"},
                citations=[{"note_id": 4, "title": "Product roadmap"}],
            )

        first_replies = [
            completion(tool_name="get_note", arguments='{"note_id": 4}', call_id="read-1"),
            completion(content="Here is the roadmap."),
        ]
        first_ctx = ChatCtx(7, now, timezone.utc, "en")
        with patch.object(chat_model, "complete", side_effect=first_replies), \
                patch.object(chat_read, "execute_tool", side_effect=read_tool):
            first = chat_loop.invoke(
                graph, graph_config,
                chat_initial_state(
                    first_ctx, [{"role": "user", "content": "Show the roadmap"}]),
            )

        planner = Mock(return_value={
            "name": "enrich_note", "args": {"note_id": 4}, "summary": "Enrich note 4",
        })
        second_messages = [*first["messages"],
                           {"role": "user", "content": "Enrich that note"}]
        with patch.object(chat_model, "complete", return_value=completion(
                tool_name="perform_action",
                arguments='{"instruction": "Enrich that note"}', call_id="write-1")), \
                patch.object(chat_dispatch.registry.get("enrich"), "plan_action", planner):
            second = chat_loop.invoke(
                graph, graph_config,
                chat_initial_state(
                    ChatCtx(7, now, timezone.utc, "en"), second_messages,
                    reference_notes=first["reference_notes"]),
            )

        self.assertEqual([4], planner.call_args.args[1]["referenced_note_ids"])
        self.assertEqual([], second["citations"])
        self.assertEqual("confirm", second["status"])

    def test_enrich_planner_can_read_note_before_validated_write(self):
        ctx = EnrichCtx(7, "now", tz="UTC", locale="en")
        replies = [
            completion(tool_name="get_note_context", arguments='{"note_id": 4}',
                       call_id="read-1"),
            completion(tool_name="set_note_path",
                       arguments='{"note_id": 4, "path": "Projects"}',
                       call_id="write-1"),
        ]
        create = Mock(side_effect=replies)
        client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=create)))
        with patch.object(enrich_model.model_gateway, "chat_completion",
                          side_effect=client.chat.completions.create), \
                patch.object(enrich_read, "execute_tool",
                             return_value='{"id": 4, "title": "Roadmap"}') as read, \
                patch.object(enrich_write.db, "get_note_for_user",
                             return_value={"id": 4}):
            result = enrich_loop.ACTION_PLAN_GRAPH.invoke({
                "messages": [{"role": "user", "content": "Move that note"}],
                "context": enrich_context_data(ctx),
                "tool_specs": enrich_tools.TOOL_SPECS,
                "steps": 0, "tool_call": None, "action": None,
            })
            action = result.get("action")

        self.assertEqual("set_note_path", action["name"])
        self.assertEqual(4, action["args"]["note_id"])
        read.assert_called_once_with(
            ANY,
            ANY,
            "get_note_context",
            {"note_id": 4},
            "enrich",
        )
        self.assertEqual(2, create.call_count)

    def test_enrich_planner_rejects_note_not_owned_by_user(self):
        ctx = EnrichCtx(7, "now", tz="UTC", locale="en")
        replies = [
            completion(tool_name="enrich_note", arguments='{"note_id": 999}'),
            completion(content="I need the note id."),
        ]
        client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=Mock(side_effect=replies))))
        with patch.object(enrich_model.model_gateway, "chat_completion",
                          side_effect=client.chat.completions.create), \
                patch.object(enrich_write.db, "get_note_for_user", return_value=None):
            result = enrich_loop.ACTION_PLAN_GRAPH.invoke({
                "messages": [{"role": "user", "content": "Enrich that note"}],
                "context": enrich_context_data(ctx),
                "tool_specs": enrich_tools.TOOL_SPECS,
                "steps": 0, "tool_call": None, "action": None,
            })
            action = result.get("action")

        self.assertIsNone(action)
        second_messages = client.chat.completions.create.call_args_list[1].kwargs["messages"]
        self.assertIn("valid user-owned note id", second_messages[-1]["content"])

    def test_reminder_resolves_second_referenced_note(self):
        now = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
        contract = {
            "instruction": "Remind me about the second one tomorrow",
            "conversation_summary": "Two notes were discussed.",
            "referenced_note_ids": [10, 20],
            "citations": [], "resolved_entities": {"specialist_mode": "reminder"},
            "locale": "en", "timezone": "UTC", "now": now.isoformat(),
        }

        def note(_user_id, note_id):
            return {"note_id": note_id, "title": "First" if note_id == 10 else "Second",
                    "text": "", "path": "Projects"}

        remind_at = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
        action = {"name": "create_reminder",
                  "args": {"text": "Remind me about the second one tomorrow\n"
                                   "Referenced note: “Second” (id 20).",
                           "remind_at": remind_at.isoformat(), "note_id": 20},
                  "summary": "Create a reminder."}
        with patch.object(enrich_service.db, "get_note_for_user", side_effect=note), \
                patch.object(enrich_service.loop.REMINDER_PLAN_GRAPH, "invoke",
                             return_value={"action": action}) as graph:
            action = enrich_service.plan_action(7, contract, now, timezone.utc, "en")

        self.assertEqual([10, 20],
                         graph.call_args.args[0]["contract"]["referenced_note_ids"])
        self.assertIn("Second", action["args"]["text"])
        self.assertEqual(20, action["args"]["note_id"])
        self.assertIn("(id 20)", action["args"]["text"])
        self.assertNotIn("(id 10)", action["args"]["text"])


if __name__ == "__main__":
    unittest.main()
