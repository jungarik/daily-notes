"""The Telegram bot's one-shot enrichment decides type, title and path — and
nothing else.

Tags and priority are not produced by the bot any more: the prompt does not ask
for them, the result carries none, the write leaves a note's existing ones
alone, and the reply message shows neither. The section's helper cannot be
imported here (its database layer needs psycopg), so the pure functions under
test are lifted out of the source and run for real, and the rest is checked
from source like the other section tests.
"""

import ast
import re
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parents[1]
SECTION = ROOT / "api" / "telegram_bot"
HELPER = (SECTION / "helper.py").read_text(encoding="utf-8")
DB_SOURCE = (SECTION / "db.py").read_text(encoding="utf-8")
BOT = (ROOT / "capture" / "Telegram_Bot" / "bot.py").read_text(encoding="utf-8")

PURE = ("_clean_path", "_enforce_root", "_normalize", "_fmt_vocab", "_vocabulary",
        "_neighbour_hint", "_similar_block")


def _load_pure_functions() -> dict:
    """The helper's pure enrichment functions and the constants they read."""
    tree = ast.parse(HELPER)
    keep = [
        node for node in tree.body
        if (isinstance(node, ast.FunctionDef) and node.name in PURE)
        or (isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_TYPES" for target in node.targets))
    ]
    namespace = {"Counter": Counter}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "helper", "exec"), namespace)

    return namespace


FUNCS = _load_pure_functions()


class ResultTests(unittest.TestCase):
    def test_the_result_is_type_title_and_path_only(self):
        meta = FUNCS["_normalize"]({
            "type": "idea", "title": "A title", "path": "Projects/api",
            "tags": ["x", "y"], "priority": "high",
        }, "text", {"Projects": ""}, "Inbox")

        self.assertEqual({"type", "title", "path"}, set(meta))
        self.assertEqual("Projects/api", meta["path"])

    def test_a_model_that_still_sends_tags_is_ignored(self):
        meta = FUNCS["_normalize"]({"tags": ["a"], "priority": "high"}, "hello", None, "Inbox")

        self.assertNotIn("tags", meta)
        self.assertNotIn("priority", meta)


class PromptTests(unittest.TestCase):
    def test_the_prompt_does_not_ask_for_tags_or_priority(self):
        system = HELPER.split("def _enrich(", 1)[1].split("resp = get_client()", 1)[0]

        self.assertNotIn("tags", system)
        self.assertNotIn("priority", system)

    def test_hints_mention_paths_and_no_tags(self):
        neighbours = [{"path": "Areas/home", "tags": ["a"], "title": "t", "note_type": "note"}]
        hint = FUNCS["_neighbour_hint"](neighbours) + FUNCS["_similar_block"](neighbours)
        vocabulary = FUNCS["_vocabulary"]([("Areas/home", 3)])

        self.assertIn("Areas/home", hint)
        self.assertIn("Areas/home", vocabulary)
        self.assertNotRegex(hint + vocabulary, r"(?i)\btags?\b")

    def test_the_tag_vocabulary_read_is_gone(self):
        self.assertNotIn("list_tags", HELPER + DB_SOURCE)


class WriteTests(unittest.TestCase):
    def test_enrichment_writes_type_title_and_path_only(self):
        block = DB_SOURCE.split("def set_enrichment", 1)[1].split("\ndef ", 1)[0]
        sql = re.search(r'"(UPDATE notes SET[^"]+)"', block).group(1)

        self.assertEqual("UPDATE notes SET note_type = %s, title = %s, path = %s WHERE id = %s;", sql)
        self.assertNotIn("priority", sql)
        self.assertNotIn("tags", sql)

    def test_the_old_overwriting_write_is_gone(self):
        self.assertNotIn("set_metadata", HELPER + DB_SOURCE)
        self.assertIn("db.set_enrichment(note_id, meta[\"type\"], meta[\"title\"], meta[\"path\"])", HELPER)

    def test_similar_notes_no_longer_select_tags(self):
        block = DB_SOURCE.split("def similar_notes", 1)[1].split("def candidate_notes", 1)[0]

        self.assertNotIn("tags", block)


class ReplyTests(unittest.TestCase):
    def test_the_message_shows_neither_tags_nor_priority(self):
        line = BOT.split("def _meta_line", 1)[1].split("\nasync def ", 1)[0]

        self.assertNotIn("tags", line)
        self.assertNotIn("priority", line)
        self.assertNotIn("🏷", line)
        self.assertNotIn("⚡", line)

    def test_link_suggestions_still_use_tags_a_note_already_has(self):
        self.assertIn("_TAG_BOOST", HELPER)


if __name__ == "__main__":
    unittest.main()
