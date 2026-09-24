"""The finder's read tools, and the prompt that drives them.

Ported from the conversation controller's suite: the tools and the prompt
moved to `tools/finder/` and `agents/finder/` unchanged, so these regressions
still apply — only the names they import did.
"""

import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from common import helper
from agents.contracts import ToolResult
from agents.finder import prompts
from agents.finder.state import FinderContext, apply_tool_result, tool_context
from tools import finder as tools
from tools.finder import get_note, list_agenda, list_paths, neighbors, search_notes
from tools.finder.specs import READ_TOOL_SPECS
from agents.runtime.execute_tool import execute_tool


def tool_text(result) -> str:
    if isinstance(result, ToolResult):
        return helper.json_text(result.data)

    return str(result)


class FinderToolTests(unittest.TestCase):
    def test_agenda_is_an_explicit_read_tool(self):
        spec = next(item for item in READ_TOOL_SPECS
                    if item["function"]["name"] == "list_agenda")
        self.assertEqual(["start_at", "end_at"],
                         spec["function"]["parameters"]["required"])

    def test_agenda_queries_range_and_cites_its_notes(self):
        ctx = FinderContext(
            7, datetime(2026, 9, 1, 10, tzinfo=timezone.utc), timezone.utc, "en")
        rows = [{"reminder_id": 3, "note_id": 9,
                 "remind_at": datetime(2026, 9, 2, 9, tzinfo=timezone.utc),
                 "text": "Call Alex", "title": "Call Alex", "status": "scheduled"}]
        args = {"start_at": "2026-09-02T00:00:00+00:00",
                "end_at": "2026-09-03T00:00:00+00:00"}
        with patch.object(list_agenda.db, "agenda_reminders", return_value=rows) as query:
            result = execute_tool(
                tools.TOOLS,
                tool_context(ctx),
                "list_agenda",
                args,
                "finder",
            )
            apply_tool_result(ctx, result)
            result = tool_text(result)

        self.assertEqual(3, json.loads(result)["reminders"][0]["reminder_id"])
        query.assert_called_once_with(
            7, datetime(2026, 9, 2, tzinfo=timezone.utc),
            datetime(2026, 9, 3, tzinfo=timezone.utc))
        self.assertEqual(
            [{"note_id": 9, "title": "Call Alex", "path": None, "date": None}],
            ctx.citations)

    def test_semantic_search_no_longer_parses_agenda_dates(self):
        with patch.object(search_notes.embedings, "embed", return_value="vector"), \
                patch.object(search_notes.db, "search_chunks", return_value=[]) as search:
            ctx = FinderContext(7, datetime.now(timezone.utc), timezone.utc, "en")
            result = execute_tool(
                tools.TOOLS,
                tool_context(ctx),
                "search_notes",
                {"query": "garden"},
                "finder",
            )
            apply_tool_result(ctx, result)
            result = tool_text(result)

        self.assertEqual("No relevant notes found.", json.loads(result)["message"])
        search.assert_called_once_with(7, "vector")

    def test_search_returns_evidence_without_a_nested_chat_completion(self):
        ctx = FinderContext(7, datetime.now(timezone.utc), timezone.utc, "en")
        hits = [{"chunk_id": 2, "note_id": 9, "content": "Grow basil",
                 "rank": 1, "similarity": 0.91,
                 "created_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
                 "remind_at": None, "source_type": "text"}]
        briefs = [{"id": 9, "title": "Balcony garden", "text": "Grow basil",
                   "path": "Areas/Garden"}]
        with patch.object(search_notes.embedings, "embed", return_value="vector"), \
                patch.object(search_notes.db, "search_chunks", return_value=hits), \
                patch.object(search_notes.db, "notes_brief", return_value=briefs), \
                patch.object(search_notes.embedings, "get_client",
                             side_effect=AssertionError("nested LLM call")):
            result = execute_tool(
                tools.TOOLS,
                tool_context(ctx),
                "search_notes",
                {"query": "garden"},
                "finder",
            )
            apply_tool_result(ctx, result)
            result = json.loads(tool_text(result))

        self.assertEqual("Grow basil", result["evidence"][0]["content"])
        self.assertEqual("Balcony garden", result["evidence"][0]["title"])
        self.assertEqual(
            [{"note_id": 9, "title": "Balcony garden",
              "path": "Areas/Garden", "date": "2026-08-01T00:00:00+00:00"}],
            ctx.citations)

    def test_read_tools_validate_context_and_args_values(self):
        context = {
            "user_id": 7,
        }

        with patch.object(get_note.db, "get_note_for_user") as note, \
                patch.object(search_notes.embedings, "embed") as embed, \
                patch.object(list_paths.db, "list_paths") as paths:
            self.assertEqual(
                "Error: context is missing required values: user_id.",
                get_note.invoke({}, {"note_id": 4}).data["error"],
            )
            self.assertEqual(
                "Error: args is missing required values: query.",
                search_notes.invoke(context, {"query": ""}).data["error"],
            )
            self.assertEqual(
                "Error: args must be an object.",
                list_paths.invoke({"user_id": 7}, None).data["error"],
            )

        note.assert_not_called()
        embed.assert_not_called()
        paths.assert_not_called()

    def test_neighbors_returns_each_linked_note_whole(self):
        """A Zettelkasten answer usually sits one link away, and the step budget
        does not stretch to a `get_note` per neighbour — so the text has to come
        back with the link."""
        created = datetime(2026, 9, 1, 9, tzinfo=timezone.utc)
        rows = [(9, "Postgres tuning", "shared_buffers to 25%",
                 "Tech/Databases", created, "out", 4)]

        with patch.object(neighbors.db, "links_of_for_user", return_value=rows):
            result = neighbors.invoke({"user_id": 7}, {"note_id": 3})

        note = result.data["notes"][0]
        self.assertEqual("shared_buffers to 25%", note["text"])
        self.assertEqual("Tech/Databases", note["path"])
        self.assertEqual("2026-09-01T09:00:00+00:00", note["date"])
        self.assertEqual(4, note["links"], "the hub hint the prompt sorts on")
        self.assertEqual("out", note["direction"])
        self.assertFalse(result.data["truncated"])
        self.assertEqual([9], [item["note_id"] for item in result.citations])

    def test_neighbors_caps_the_list_and_says_so(self):
        """Full text is unbounded per note, so the cap is what keeps one tool
        result a predictable size. A reader that cannot tell a full page from an
        exact fit would report a hub's links as complete."""
        created = datetime(2026, 9, 1, 9, tzinfo=timezone.utc)
        rows = [(i, f"n{i}", "text", "Tech", created, "out", 1)
                for i in range(neighbors.LIMIT + 1)]

        with patch.object(neighbors.db, "links_of_for_user",
                          return_value=rows) as query:
            result = neighbors.invoke({"user_id": 7}, {"note_id": 3})

        self.assertEqual(neighbors.LIMIT + 1, query.call_args[0][2],
                         "asks for one more than the cap to detect a full page")
        self.assertEqual(neighbors.LIMIT, len(result.data["notes"]))
        self.assertTrue(result.data["truncated"])

    def test_neighbors_reports_an_unlinked_note_as_such(self):
        with patch.object(neighbors.db, "links_of_for_user", return_value=[]):
            result = neighbors.invoke({"user_id": 7}, {"note_id": 3})

        self.assertEqual("No linked notes.", result.data["message"])
        self.assertEqual([], list(result.citations))

    def test_the_prompt_exposes_current_local_time(self):
        now = datetime(2026, 9, 1, 12, 30, tzinfo=timezone.utc)
        messages = prompts.with_system(
            [{"role": "user", "content": "What is tomorrow's agenda?"}],
            now, timezone.utc)
        self.assertIn("2026-09-01T12:30:00+00:00", messages[0]["content"])
        self.assertIn("list_agenda", messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
