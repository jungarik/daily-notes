"""The classifier's pipeline, and the deterministic write it proposes.

These moved wholesale from `test_enricher_metadata.py`: the three nodes and
the `enrich_note` write they resolve are the classifier's now, and the
standalone graph the first test drives is no longer a graph nothing invokes.
"""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import config
from agents.classifier import agent as classifier_agent
from agents.classifier import graph as classify_graph
from agents.classifier.nodes import gather, propose
from agents.contracts import AgentRequest, build_context
from tools import classifier as classifier_tools
from tools.classifier import CONTEXT_TOOLS, TOOL_SPECS
from tools.classifier import enrich_note, find_related_notes, get_vault_context
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


CONTEXT = build_context(7, "2026-09-01T10:00:00+03:00", tz="Europe/Kiev", locale="en")


def _request(**references):
    """One turn's envelope, with no earlier hops.

    An empty `history` is what keeps these tests off the `read_state` path: the
    note is named by the client, so nothing has to be recovered from a peer.
    """
    return AgentRequest(
        request_id="req-1",
        correlation_id="turn-1",
        causation_id=None,
        agent="classifier",
        message="file this note",
        context=CONTEXT,
        references=references,
        history=(),
        hops_left=4)


class ClassifyPipelineTests(unittest.TestCase):
    def test_metadata_context_tools_are_internal_and_own_retrieval(self):
        exposed = {spec["function"]["name"] for spec in TOOL_SPECS}
        self.assertNotIn("get_vault_context", exposed)
        self.assertNotIn("find_related_notes", exposed)
        self.assertIn("find_related_notes", CONTEXT_TOOLS)
        ctx = build_context(7, "now", tz="UTC", locale="en")
        with patch.object(find_related_notes.embedings, "embed", return_value="vector"), \
                patch.object(find_related_notes.db, "related_notes", return_value=[]) as related:
            result = execute_allowed_tool(
                classifier_tools.TOOLS,
                CONTEXT_TOOLS,
                ctx,
                "find_related_notes",
                {"text": "Garden", "exclude_note_id": None},
                "classifier",
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
        with patch.object(gather, "execute_allowed_tool", context_tool), \
                patch.object(propose.model_gateway, "chat_completion",
                             side_effect=client.chat.completions.create):
            result = classify_graph.CLASSIFY_GRAPH.invoke({
                # One entry shape. The bare `user_id` this used to pass was the
                # second way into the metadata pipeline, and it went with the
                # split — the agent has one `start`, so the graph takes the
                # turn's context like every other graph in the farm.
                "user_context": CONTEXT,
                "text": "Build a pocket garden",
                "note_id": None,
                "trace": [],
            })

        self.assertEqual("Pocket garden", result["metadata"]["title"])
        self.assertEqual(["garden"], result["metadata"]["tags"])
        self.assertEqual(
            ["gather", "propose", "normalize"],
            [event["node"] for event in result["trace"]
             if event.get("kind") == "node"])
        self.assertEqual(
            ["list_paths", "list_tags", "get_vault_context", "find_related_notes"],
            [event["tool"] for event in result["trace"]
             if event.get("kind") == "tool"])
        self.assertEqual(
            {"gather", "propose", "normalize"},
            set(classify_graph.CLASSIFY_GRAPH.get_graph().nodes) -
            {"__start__", "__end__"})

    def test_the_agent_pauses_with_the_exact_metadata_it_will_write(self):
        """What the user confirms is what `resume` writes.

        The action's args carry the metadata itself, not just the note id, so
        there is no second model call between the summary the user reads and
        the values that reach the database."""
        proposed = {"type": "task", "title": "Ship release", "path": "Projects/App",
                    "tags": ["release"], "priority": "high"}
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=Mock(return_value=completion(content=json.dumps(proposed))))))
        note = {"id": 4, "text": "Ship the app release", "title": None,
                "path": None, "tags": [], "type": None, "priority": None}
        context_results = {
            "get_note_context": note, "list_paths": [], "list_tags": [],
            "get_vault_context": {"root_folders": {"Projects": "projects"},
                                  "default_root": "Projects"},
            "find_related_notes": [],
        }
        context_tool = Mock(side_effect=lambda _registry, _allowed, _ctx, name, _args, _owner:
                            json.dumps(context_results[name]))
        request = _request(referenced_note_ids=[4])

        with patch.object(gather, "execute_allowed_tool", context_tool), \
                patch.object(propose.model_gateway, "chat_completion",
                             side_effect=client.chat.completions.create):
            result = classifier_agent.start(request)

        action = result.state["planned"]
        self.assertEqual("needs_input", result.status)
        self.assertEqual("enrich_note", action["name"])
        self.assertEqual(4, action["args"]["note_id"])
        self.assertEqual("Ship release", action["args"]["title"])
        self.assertEqual("high", action["args"]["priority"])
        self.assertIn("Ship release", action["summary"])

    def test_a_turn_naming_no_note_plans_nothing(self):
        """There is no note to file, which is an ordinary outcome — the turn
        finishes without a write rather than failing."""
        result = classifier_agent.start(_request())

        self.assertEqual("done", result.status)
        self.assertIsNone(result.state["planned"])

    def test_confirmed_metadata_persistence_does_not_call_llm(self):
        proposed = {"type": "task", "title": "Ship release", "path": "Projects/App",
                    "tags": ["release"], "priority": "high"}
        note = {"id": 4, "text": "Ship the app release"}
        with patch.object(enrich_note.db, "get_note_for_user", return_value=note), \
                patch.object(enrich_note.db, "set_metadata") as save, \
                patch.object(find_related_notes.embedings, "embed",
                             side_effect=AssertionError("Embedding during confirmation")):
            result = enrich_note.invoke(
                build_context(7, "now"),
                {"note_id": 4, **proposed},
            ).data

        self.assertEqual("Ship release", result["title"])
        save.assert_called_once_with(
            4, "task", "Ship release", "high", ["release"], "Projects/App")


class LocaleTests(unittest.TestCase):
    """Folder names are localised and then written into the note's path, so the
    locale that builds the roster and the locale that normalises the write have
    to be the same one — the caller's."""

    def test_the_vault_roots_follow_the_callers_locale(self):
        english = get_vault_context.invoke(
            build_context(7, "now", locale="en"), {}).data
        ukrainian = get_vault_context.invoke(
            build_context(7, "now", locale="uk"), {}).data

        self.assertEqual("Inbox", english["default_root"])
        self.assertEqual("Вхідні", ukrainian["default_root"])
        self.assertIn("Вхідні", ukrainian["root_folders"])

    def test_the_write_normalises_against_the_same_locale(self):
        """The bug this guards: the proposal said Вхідні, the write resolved its
        own locale, did not recognise it as a root, and replaced it with Inbox."""
        note = {"id": 4, "text": "a thought"}
        proposed = {"type": "note", "title": "A thought", "path": "Вхідні",
                    "tags": [], "priority": "normal"}

        with patch.object(enrich_note.db, "get_note_for_user", return_value=note), \
                patch.object(enrich_note.db, "set_metadata") as save:
            enrich_note.invoke(
                build_context(7, "now", locale="uk"),
                {"note_id": 4, **proposed},
            )

        self.assertEqual("Вхідні", save.call_args[0][5])


if __name__ == "__main__":
    unittest.main()
