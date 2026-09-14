"""Native LangGraph interrupt/resume regression tests."""

import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from langgraph.checkpoint.memory import InMemorySaver

from agents.runtime import checkpoint
from agents.runtime import loop as agent_loop
from agents import bootstrap
from agents.runtime import execution_ledger
from agents.conversation import graph as chat_loop
from agents.conversation import api as chat_service
from agents.conversation.nodes import approve as chat_approve
from agents.conversation.nodes import handoff as chat_handoff
from agents.conversation.nodes import reason as chat_reason
from agents.conversation.state import initial_state as chat_initial_state
from agents.enrich import graph as enrich_loop
from agents.enrich.nodes import approve as enrich_approve
from agents.enrich.nodes import reason as enrich_reason


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
    def test_graph_config_scopes_and_bounds_the_run(self):
        self.assertEqual(
            {"configurable": {"thread_id": "chat:42"}, "recursion_limit": 23},
            checkpoint.graph_config("chat", 42, 6),
        )

    def test_graph_config_keeps_a_floor_under_a_small_step_budget(self):
        self.assertEqual(20, checkpoint.graph_config("enrich", 1, 1)["recursion_limit"])

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
        with patch.object(chat_reason.model_gateway, "chat_completion", side_effect=replies), \
                patch.object(bootstrap.registry.get("enrich"), "plan_action",
                             return_value=action) as plan, \
                patch.object(execution_ledger, "execute_once",
                             side_effect=lambda *args: args[-1]()), \
                patch.object(bootstrap.registry.get("enrich"), "execute_action",
                             return_value='{"note_id": 9}') as execute:
            paused = agent_loop.invoke(
                graph, graph_config,
                chat_initial_state(
                    context(), [{"role": "user", "content": "Save Idea"}]),
            )
            snapshot = graph.get_state(graph_config)
            action_id = paused["pending"]["action_id"]
            resumed = agent_loop.resume(graph, graph_config, True)

        self.assertTrue(checkpoint.has_interrupts(snapshot.tasks))
        self.assertEqual(("approve",), snapshot.next)
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
        with patch.object(enrich_reason.model_gateway, "chat_completion", side_effect=replies), \
                patch.object(enrich_approve.execution_ledger, "execute_once",
                             return_value='{"note_id": 10}') as execute_once:
            paused = agent_loop.invoke(
                graph, graph_config,
                enrich_loop.initial_state(
                    context(), [{"role": "user", "content": "Save Idea"}]),
            )
            snapshot = graph.get_state(graph_config)
            resumed = agent_loop.resume(graph, graph_config, True)

        self.assertTrue(checkpoint.has_interrupts(snapshot.tasks))
        self.assertEqual(paused["pending"]["action_id"],
                         snapshot.values["pending"]["action_id"])
        self.assertEqual("Created.", resumed["reply"])
        execute_once.assert_called_once()

    def test_chat_agent_resumes_postgres_style_session_by_thread_id(self):
        """The agent takes thread data in and hands a result back; the calling
        section owns the projection. This test plays that section."""
        saver = InMemorySaver()
        projection = {"id": 51, "messages": [], "pending": None}

        @contextmanager
        def saver_session():
            yield saver

        def persist(result):
            projection.update(
                messages=result.get("messages") or [],
                pending=result.get("pending"),
            )

            return result

        action = {"name": "create_note", "args": {"text": "Idea"},
                  "summary": "Create a note"}
        replies = [
            completion(tool_name="perform_action",
                       arguments='{"instruction": "save Idea"}'),
            completion(content="Created."),
        ]
        now = datetime(2026, 8, 31, tzinfo=timezone.utc)
        with patch.object(chat_service.checkpoint, "saver_session",
                          side_effect=saver_session), \
                patch.object(chat_reason.model_gateway, "chat_completion", side_effect=replies), \
                patch.object(bootstrap.registry.get("enrich"), "plan_action",
                             return_value=action), \
                patch.object(execution_ledger, "execute_once",
                             side_effect=lambda *args: args[-1]()), \
                patch.object(bootstrap.registry.get("enrich"), "execute_action",
                             return_value='{"note_id": 11}') as execute:
            paused = persist(chat_service.run_turn(
                51, [], None, "Save Idea", 7, now, timezone.utc, "en"))
            resumed = persist(chat_service.run_confirmation(
                51, list(projection["messages"]), projection["pending"],
                True, None, 7, now, timezone.utc, "en"))
            repeated = persist(chat_service.run_confirmation(
                51, list(projection["messages"]), projection["pending"],
                True, None, 7, now, timezone.utc, "en"))

        self.assertEqual("confirm", paused["status"])
        self.assertEqual("Created.", resumed["reply"])
        self.assertEqual("Created.", repeated["reply"])
        execute.assert_called_once()
        self.assertIsNone(projection["pending"])

    def test_agent_surface_performs_no_thread_persistence(self):
        """The conversation surface must not reach for the thread projection."""
        self.assertFalse(hasattr(chat_service, "db"))


if __name__ == "__main__":
    unittest.main()
