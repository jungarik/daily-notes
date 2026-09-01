"""Explicit Conversation agenda tool regressions."""

import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from agents.conversation import prompts
from agents.conversation.state import ConversationContext
from agents.conversation.tools import handlers
from agents.conversation.tools.specs import READ_TOOL_SPECS


class ConversationAgendaTests(unittest.TestCase):
    def test_agenda_is_an_explicit_read_tool(self):
        spec = next(item for item in READ_TOOL_SPECS
                    if item["function"]["name"] == "list_agenda")
        self.assertEqual(["start_at", "end_at"],
                         spec["function"]["parameters"]["required"])

    def test_agenda_queries_range_and_cites_its_notes(self):
        ctx = ConversationContext(
            7, datetime(2026, 9, 1, 10, tzinfo=timezone.utc), timezone.utc, "en")
        rows = [{"reminder_id": 3, "note_id": 9,
                 "remind_at": datetime(2026, 9, 2, 9, tzinfo=timezone.utc),
                 "text": "Call Alex", "title": "Call Alex", "status": "scheduled"}]
        args = {"start_at": "2026-09-02T00:00:00+00:00",
                "end_at": "2026-09-03T00:00:00+00:00"}
        with patch.object(handlers.db, "agenda_reminders", return_value=rows) as query:
            result = handlers.execute_tool(ctx, "list_agenda", args)

        self.assertEqual(3, json.loads(result)[0]["reminder_id"])
        query.assert_called_once_with(
            7, datetime(2026, 9, 2, tzinfo=timezone.utc),
            datetime(2026, 9, 3, tzinfo=timezone.utc))
        self.assertEqual([{"note_id": 9, "title": "Call Alex"}], ctx.citations)

    def test_semantic_search_no_longer_parses_agenda_dates(self):
        with patch.object(handlers, "_embed", return_value="vector"), \
                patch.object(handlers.db, "search_chunks", return_value=[]) as search:
            ctx = ConversationContext(7, datetime.now(timezone.utc), timezone.utc, "en")
            result = handlers.execute_tool(ctx, "search_notes", {"query": "garden"})

        self.assertEqual("No relevant notes found.", result)
        search.assert_called_once_with(7, "vector")

    def test_search_returns_evidence_without_a_nested_chat_completion(self):
        ctx = ConversationContext(7, datetime.now(timezone.utc), timezone.utc, "en")
        hits = [{"chunk_id": 2, "note_id": 9, "content": "Grow basil",
                 "rank": 1, "similarity": 0.91,
                 "created_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
                 "remind_at": None, "source_type": "text"}]
        briefs = [{"id": 9, "title": "Balcony garden", "text": "Grow basil",
                   "path": "Areas/Garden"}]
        with patch.object(handlers, "_embed", return_value="vector"), \
                patch.object(handlers.db, "search_chunks", return_value=hits), \
                patch.object(handlers.db, "notes_brief", return_value=briefs), \
                patch.object(handlers, "get_client",
                             side_effect=AssertionError("nested LLM call")):
            result = json.loads(handlers.execute_tool(
                ctx, "search_notes", {"query": "garden"}))

        self.assertEqual("Grow basil", result["evidence"][0]["content"])
        self.assertEqual("Balcony garden", result["evidence"][0]["title"])
        self.assertEqual([{"note_id": 9, "title": "Balcony garden"}], ctx.citations)

    def test_conversation_prompt_exposes_current_local_time(self):
        now = datetime(2026, 9, 1, 12, 30, tzinfo=timezone.utc)
        messages = prompts.with_system(
            [{"role": "user", "content": "What is tomorrow's agenda?"}],
            now, timezone.utc)
        self.assertIn("2026-09-01T12:30:00+00:00", messages[0]["content"])
        self.assertIn("list_agenda", messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
