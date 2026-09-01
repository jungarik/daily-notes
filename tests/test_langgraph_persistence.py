"""Native LangGraph interrupt/resume regression tests."""

import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from langgraph.checkpoint.memory import InMemorySaver

from agents.runtime import checkpoint
from agents.conversation import graph as chat_loop
from agents.conversation import api as chat_service
from agents.conversation.nodes import approval as chat_approval
from agents.conversation.nodes import dispatch as chat_dispatch
from agents.conversation.nodes import model as chat_model
from agents.conversation.state import initial_state as chat_initial_state
from agents.enrich import graph as enrich_loop
from agents.enrich.nodes import approval as enrich_approval
from agents.enrich.nodes import model as enrich_model


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
    return SimpleNamespace(
        user_id=7, now="2026-08-31T10:00:00+03:00", tz="Europe/Kiev", locale="en",
        citations=[], _cited=set(),
        trace={"tools": [], "retrieved_chunks": [], "routes": []},
        record_tool=lambda *args: None, record_route=lambda *args: None,
    )


class LangGraphPersistenceTests(unittest.TestCase):
    def test_chat_resumes_same_checkpoint_without_replanning_action(self):
        saver = InMemorySaver()
        graph = chat_loop.build_graph(saver)
        graph_config = {"configurable": {"thread_id": "chat:42"}}
        action = {"name": "create_note", "args": {"text": "Idea"},
                  "summary": "Create a note"}
        replies = [
            completion(tool_name="perform_action",
                       arguments='{"instruction": "save Idea"}'),
            completion(content="Created."),
        ]
        with patch.object(chat_model, "complete", side_effect=replies), \
                patch.object(chat_dispatch.registry.get("enrich"), "plan_action",
                             return_value=action) as plan, \
                patch.object(chat_approval.execution_ledger, "execute_once",
                             side_effect=lambda *args: args[-1]()), \
                patch.object(chat_approval.registry.get("enrich"), "execute_action",
                             return_value='{"note_id": 9}') as execute:
            paused = chat_loop.invoke(
                graph, graph_config,
                chat_initial_state(
                    context(), [{"role": "user", "content": "Save Idea"}]),
            )
            snapshot = graph.get_state(graph_config)
            action_id = paused["pending"]["action_id"]
            resumed = chat_loop.resume(graph, graph_config, True)

        self.assertTrue(checkpoint.is_interrupted(snapshot))
        self.assertEqual(("approval",), snapshot.next)
        self.assertEqual(action_id, snapshot.values["pending"]["action_id"])
        self.assertEqual("Created.", resumed["reply"])
        plan.assert_called_once()
        execute.assert_called_once()

    def test_enrich_uses_interrupt_and_command_resume(self):
        graph = enrich_loop.build_graph(InMemorySaver())
        graph_config = {"configurable": {"thread_id": "enrich:43"}}
        replies = [
            completion(tool_name="create_note", arguments='{"text": "Idea"}'),
            completion(content="Created."),
        ]
        with patch.object(enrich_model, "complete", side_effect=replies), \
                patch.object(enrich_approval.execution_ledger, "execute_once",
                             return_value='{"note_id": 10}') as execute_once:
            paused = enrich_loop.invoke(
                graph, graph_config,
                enrich_loop.initial_state(
                    context(), [{"role": "user", "content": "Save Idea"}]),
            )
            snapshot = graph.get_state(graph_config)
            resumed = enrich_loop.resume(graph, graph_config, True)

        self.assertTrue(checkpoint.is_interrupted(snapshot))
        self.assertEqual(paused["pending"]["action_id"],
                         snapshot.values["pending"]["action_id"])
        self.assertEqual("Created.", resumed["reply"])
        execute_once.assert_called_once()

    def test_chat_service_resumes_postgres_style_session_by_thread_id(self):
        saver = InMemorySaver()
        projection = {"id": 51, "messages": [], "pending": None}

        @contextmanager
        def session(build_graph, namespace, thread_id):
            self.assertEqual("chat", namespace)
            graph = build_graph(saver)
            yield graph, {"configurable": {"thread_id": f"{namespace}:{thread_id}"}}

        def save_thread(thread_id, messages, pending):
            projection.update(id=thread_id, messages=messages, pending=pending)

        action = {"name": "create_note", "args": {"text": "Idea"},
                  "summary": "Create a note"}
        replies = [
            completion(tool_name="perform_action",
                       arguments='{"instruction": "save Idea"}'),
            completion(content="Created."),
        ]
        now = datetime(2026, 8, 31, tzinfo=timezone.utc)
        with patch.object(chat_service.checkpoint, "session", side_effect=session), \
                patch.object(chat_service.db, "create_thread", return_value=51), \
                patch.object(chat_service.db, "get_thread",
                             side_effect=lambda user_id, thread_id: dict(projection)), \
                patch.object(chat_service.db, "save_thread",
                             side_effect=save_thread), \
                patch.object(chat_model, "complete", side_effect=replies), \
                patch.object(chat_dispatch.registry.get("enrich"), "plan_action",
                             return_value=action), \
                patch.object(chat_approval.execution_ledger, "execute_once",
                             side_effect=lambda *args: args[-1]()), \
                patch.object(chat_approval.registry.get("enrich"), "execute_action",
                             return_value='{"note_id": 11}') as execute:
            paused = chat_service.start_turn(7, "Save Idea", None, now, timezone.utc, "en")
            resumed = chat_service.confirm(7, 51, True, now, timezone.utc, "en")
            repeated = chat_service.confirm(7, 51, True, now, timezone.utc, "en")

        self.assertEqual("confirm", paused["status"])
        self.assertEqual("Created.", resumed["reply"])
        self.assertEqual("Created.", repeated["reply"])
        execute.assert_called_once()
        self.assertIsNone(projection["pending"])


if __name__ == "__main__":
    unittest.main()
