"""Explicit Enrich metadata subgraph and deterministic execution."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import config
from agents.enrich import graph as enrich_graph
from agents.enrich.nodes.classify import gather as classify_gather
from agents.enrich.nodes.classify import propose as classify_propose
from agents.enrich.state import Ctx, context_to_dict
from tools.enrich import METADATA_CONTEXT_TOOLS, TOOL_SPECS
from tools import enrich as enrich_tools
from tools.enrich import enrich_note, find_related_notes
from agents.runtime.execute_tool import execute_allowed_tool


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
        with patch.object(find_related_notes.embedings, "embed", return_value="vector"), \
                patch.object(find_related_notes.db, "related_notes", return_value=[]) as related:
            result = execute_allowed_tool(
                enrich_tools.TOOLS,
                METADATA_CONTEXT_TOOLS,
                context_to_dict(ctx),
                "find_related_notes",
                {"text": "Garden", "exclude_note_id": None},
                "enrich",
            )
        self.assertEqual([], result.data["notes"])
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
        context_tool = Mock(side_effect=lambda _registry, _allowed, _ctx, name, _args, _owner:
                            json.dumps(context_results[name]))
        with patch.object(classify_gather, "execute_allowed_tool", context_tool), \
                patch.object(classify_propose.model_gateway, "chat_completion",
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
            ["classify_gather", "classify_propose", "classify_normalize"],
            [event["node"] for event in result["metadata_trace"]
             if event.get("kind") == "node"])
        self.assertEqual(
            ["list_paths", "list_tags", "get_vault_context", "find_related_notes"],
            [event["tool"] for event in result["metadata_trace"]
             if event.get("kind") == "tool"])
        self.assertEqual(
            {"classify_gather", "classify_propose", "classify_normalize"},
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
        context_tool = Mock(side_effect=lambda _registry, _allowed, _ctx, name, _args, _owner:
                            json.dumps(context_results[name]))
        with patch.object(classify_gather, "execute_allowed_tool", context_tool), \
                patch.object(classify_propose.model_gateway, "chat_completion",
                             side_effect=client.chat.completions.create), \
                patch("agents.enrich.nodes.write.validate.db.get_note_for_user", return_value=note):
            result = enrich_graph.ACTION_PLAN_GRAPH.invoke({
                "messages": [{"role": "user", "content": "Enrich note 4"}],
                "context": context_to_dict(ctx),
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
        with patch.object(enrich_note.db, "get_note_for_user", return_value=note), \
                patch.object(enrich_note.db, "get_language", return_value="en"), \
                patch.object(enrich_note.db, "set_metadata") as save, \
                patch.object(find_related_notes.embedings, "embed",
                             side_effect=AssertionError("Embedding during confirmation")):
            result = enrich_note.invoke(
                context_to_dict(Ctx(7, "now")),
                {"note_id": 4, **proposed},
            ).data

        self.assertEqual("Ship release", result["title"])
        save.assert_called_once_with(
            4, "task", "Ship release", "high", ["release"], "Projects/App")


if __name__ == "__main__":
    unittest.main()
