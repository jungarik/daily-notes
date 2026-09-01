"""Explicit Enrich metadata subgraph and deterministic execution."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import config
from agents.enrich import graph as enrich_graph
from agents.enrich.nodes import metadata as metadata_nodes
from agents.enrich.state import context_data
from agents.enrich.tools import Ctx, METADATA_CONTEXT_TOOLS, TOOL_SPECS
from agents.enrich.tools import handlers as tool_handlers


def completion(content=None, tool_name=None, arguments="{}", call_id="call-1"):
    calls = []
    if tool_name:
        calls.append(SimpleNamespace(
            id=call_id,
            function=SimpleNamespace(name=tool_name, arguments=arguments),
        ))
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=content, tool_calls=calls))])


class EnrichMetadataTests(unittest.TestCase):
    def test_metadata_context_tools_are_internal_and_own_retrieval(self):
        exposed = {spec["function"]["name"] for spec in TOOL_SPECS}
        self.assertNotIn("get_vault_context", exposed)
        self.assertNotIn("find_related_notes", exposed)
        self.assertIn("find_related_notes", METADATA_CONTEXT_TOOLS)
        ctx = Ctx(7, "now", tz="UTC", locale="en")
        with patch.object(tool_handlers, "_embed", return_value="vector"), \
                patch.object(tool_handlers.db, "related_notes", return_value=[]) as related:
            result = tool_handlers.execute_context_tool(
                ctx, "find_related_notes", {"text": "Garden", "exclude_note_id": None})
        self.assertEqual([], json.loads(result))
        related.assert_called_once_with(7, "vector", config.ENRICH_SIMILAR_LIMIT)

    def test_capture_metadata_runs_as_three_named_graph_nodes(self):
        raw = {"type": "idea", "title": "Pocket garden", "path": "Projects/Garden",
               "tags": ["Garden"], "priority": "med"}
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=Mock(return_value=completion(content=json.dumps(raw))))))
        related = [{"note_id": 9, "title": "Balcony", "note_type": "note",
                    "path": "Areas", "tags": ["garden"], "distance": 0.2}]
        context_results = {
            "list_paths": [], "list_tags": [],
            "get_vault_context": {"root_folders": {"Projects": "projects"},
                                  "default_root": "Projects"},
            "find_related_notes": related,
        }
        context_tool = Mock(side_effect=lambda _ctx, name, _args:
                            json.dumps(context_results[name]))
        with patch.object(metadata_nodes, "execute_context_tool", context_tool), \
                patch.object(metadata_nodes.model_gateway, "chat_completion",
                             side_effect=client.chat.completions.create):
            result = enrich_graph.METADATA_GRAPH.invoke({
                "user_id": 7,
                "metadata_text": "Build a pocket garden",
                "metadata_note_id": None,
                "metadata_trace": [],
            })

        self.assertEqual("Pocket garden", result["metadata"]["title"])
        self.assertEqual(["garden"], result["metadata"]["tags"])
        self.assertEqual(
            ["metadata_context", "metadata_model", "metadata_validation"],
            [event["node"] for event in result["metadata_trace"]
             if event.get("kind") == "node"])
        self.assertEqual(
            ["list_paths", "list_tags", "get_vault_context", "find_related_notes"],
            [event["tool"] for event in result["metadata_trace"]
             if event.get("kind") == "tool"])
        self.assertEqual(
            {"metadata_context", "metadata_model", "metadata_validation"},
            set(enrich_graph.METADATA_GRAPH.get_graph().nodes) -
            {"__start__", "__end__"})

    def test_existing_note_plan_contains_exact_metadata_before_approval(self):
        replies = [
            completion(tool_name="enrich_note", arguments='{"note_id": 4}'),
            completion(content=json.dumps({
                "type": "task", "title": "Ship release", "path": "Projects/App",
                "tags": ["release"], "priority": "high",
            })),
        ]
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=Mock(side_effect=replies))))
        note = {"id": 4, "text": "Ship the app release", "title": None,
                "path": None, "tags": [], "type": None, "priority": None}
        ctx = Ctx(7, "2026-09-01T10:00:00+03:00", tz="Europe/Kiev", locale="en")
        context_results = {
            "get_note_context": note, "list_paths": [], "list_tags": [],
            "get_vault_context": {"root_folders": {"Projects": "projects"},
                                  "default_root": "Projects"},
            "find_related_notes": [],
        }
        context_tool = Mock(side_effect=lambda _ctx, name, _args:
                            json.dumps(context_results[name]))
        with patch.object(metadata_nodes, "execute_context_tool", context_tool), \
                patch.object(metadata_nodes.model_gateway, "chat_completion",
                             side_effect=client.chat.completions.create), \
                patch("agents.enrich.nodes.write.db.get_note_for_user", return_value=note):
            result = enrich_graph.ACTION_PLAN_GRAPH.invoke({
                "messages": [{"role": "user", "content": "Enrich note 4"}],
                "context": context_data(ctx),
                "tool_specs": [{"type": "function", "function": {
                    "name": "enrich_note", "parameters": {"type": "object"}}}],
                "steps": 0, "tool_call": None, "action": None,
            })
            action = result.get("action")

        self.assertEqual("Ship release", action["args"]["title"])
        self.assertEqual("high", action["args"]["priority"])
        self.assertIn("Ship release", action["summary"])

    def test_confirmed_metadata_persistence_does_not_call_llm(self):
        proposed = {"type": "task", "title": "Ship release", "path": "Projects/App",
                    "tags": ["release"], "priority": "high"}
        note = {"id": 4, "text": "Ship the app release"}
        with patch.object(tool_handlers.db, "get_note_for_user", return_value=note), \
                patch.object(tool_handlers.db, "get_language", return_value="en"), \
                patch.object(tool_handlers.db, "set_metadata") as save, \
                patch.object(tool_handlers.embedings, "embed",
                             side_effect=AssertionError("Embedding during confirmation")):
            result = json.loads(tool_handlers._enrich_note(
            Ctx(7, "now"), {"note_id": 4, **proposed}))

        self.assertEqual("Ship release", result["title"])
        save.assert_called_once_with(
            4, "task", "Ship release", "high", ["release"], "Projects/App")


if __name__ == "__main__":
    unittest.main()
