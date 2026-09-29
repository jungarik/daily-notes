"""The header's root-folder counts: the counting rule, and the localisation.

Two things are worth pinning here. The count is *not* a note count — it is what
an explorer would show inside a root, which means sub-folders collapse to one
row each while loose notes count individually. And the match is on the stored,
localised folder name, so the label and the query have to come from the same
locale or the numbers silently read zero.

`count_root_entries`'s SQL is exercised against a real SQLite fixture rather
than a mock, because the rule lives in the query, not in Python.
"""

import re
import sqlite3
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[1]

# `api.header.db` imports the shared psycopg pool at module load; the section's
# logic is what is under test, so the connection is stubbed away.
if "db" not in sys.modules:
    stub = types.ModuleType("db")
    stub.cursor = lambda: None
    sys.modules["db"] = stub

import i18n                                  # noqa: E402
from api.header import helper                # noqa: E402


def _sqlite_ready(sql: str) -> str:
    """The section's own SQL, translated to what SQLite understands.

    Only the dialect changes — `split_part` becomes substring arithmetic, the
    aggregate FILTER becomes a CASE, `= ANY(?)` becomes an IN list. The shape of
    the rule (distinct sub-folders, plus loose notes) is left exactly as written
    so a change to it breaks this test.
    """
    sql = sql.replace("split_part(path, '/', 1)",
                      "CASE WHEN instr(path,'/') = 0 THEN path "
                      "ELSE substr(path, 1, instr(path,'/') - 1) END")
    sql = sql.replace("split_part(path, '/', 2)",
                      "CASE WHEN instr(path,'/') = 0 THEN '' "
                      "ELSE substr(path, instr(path,'/') + 1) END")
    sql = re.sub(r"count\(DISTINCT sub\) FILTER \(WHERE sub <> ''\)",
                 "count(DISTINCT CASE WHEN sub <> '' THEN sub END)", sql)
    sql = re.sub(r"count\(\*\)\s+FILTER \(WHERE sub =  ''\)",
                 "count(CASE WHEN sub = '' THEN 1 END)", sql)
    return sql.replace("%s", "?").replace("root = ANY(?)", "root IN (?, ?)")


def _count(rows, roots):
    """Run the real query over an in-memory vault. `rows` are (user_id, path)."""
    source = (ROOT / "api" / "header" / "db.py").read_text(encoding="utf-8")
    # Scope to the function first: `get_language` holds the file's own earlier
    # `cur.execute(`, and its docstring would otherwise be read as the query.
    body = source.split("def count_root_entries", 1)[1]
    sql = body.split("cur.execute(", 1)[1].split('"""')[1]

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE notes (user_id INT, path TEXT);")
    conn.executemany("INSERT INTO notes VALUES (?, ?);", rows)
    found = conn.execute(_sqlite_ready(sql), (7, *roots)).fetchall()
    conn.close()

    return {row[0]: row[1] for row in found}


class CountRuleTests(unittest.TestCase):
    def test_sub_folders_collapse_and_loose_notes_do_not(self):
        """Two sub-folders and two loose notes is four rows, not six notes."""
        counts = _count([
            (7, "Projects/Home"), (7, "Projects/Home"), (7, "Projects/Home"),
            (7, "Projects/Work"), (7, "Projects/Work"),
            (7, "Projects"), (7, "Projects"),
        ], ("Projects", "Areas"))

        self.assertEqual(4, counts["Projects"])

    def test_a_root_with_nothing_in_it_is_absent(self):
        """The query returns no row rather than a zero — the helper defaults it,
        so a missing key here must not read as a bug there."""
        counts = _count([(7, "Projects/Home")], ("Projects", "Areas"))

        self.assertNotIn("Areas", counts)

    def test_another_users_notes_are_not_counted(self):
        counts = _count([(7, "Projects/Home"), (8, "Projects/Theirs")],
                        ("Projects", "Areas"))

        self.assertEqual(1, counts["Projects"])

    def test_a_note_with_no_path_is_ignored(self):
        counts = _count([(7, "Projects"), (7, ""), (7, None)],
                        ("Projects", "Areas"))

        self.assertEqual(1, counts["Projects"])


class LocaleTests(unittest.TestCase):
    """The label and the query must come from one locale, or the counts are
    labelled in one language and matched in another."""

    def _stats(self, language, counts):
        with patch.object(helper.db, "get_language", return_value=language), \
                patch.object(helper.db, "count_root_entries",
                             return_value=counts) as counted:
            return helper.stats(7), counted.call_args[0][1]

    def test_labels_and_matched_names_are_the_same_strings(self):
        stats, matched = self._stats("uk", {})

        self.assertEqual([entry["label"] for entry in stats["stats"]], matched)

    def test_ukrainian_roots(self):
        stats, _ = self._stats("uk", {"Проєкти": 3})

        by_key = {entry["key"]: entry for entry in stats["stats"]}
        self.assertEqual("Вхідні", by_key["folder_inbox"]["label"])
        self.assertEqual("Матеріали", by_key["folder_resources"]["label"])
        self.assertEqual(3, by_key["folder_projects"]["count"])

    def test_an_unmatched_root_reports_zero(self):
        stats, _ = self._stats("uk", {})

        self.assertEqual([0, 0, 0, 0], [e["count"] for e in stats["stats"]])

    def test_no_stored_language_falls_back_to_ukrainian(self):
        """Only the bot writes `users.language`, so a Mini-App-only user has
        NULL and must still get a usable header.

        The expected string is spelled out rather than derived from
        `FALLBACK_LOCALE`: comparing the constant against itself would pass
        whatever it were changed to, which is not a test of anything."""
        stats, _ = self._stats(None, {})

        self.assertEqual("uk", helper.FALLBACK_LOCALE)
        self.assertEqual("Вхідні", stats["stats"][0]["label"])


class ShapeTests(unittest.TestCase):
    def test_four_roots_in_display_order(self):
        """The Mini App shows the first three by position, so the order is part
        of the contract rather than an implementation detail."""
        self.assertEqual(
            ("folder_inbox", "folder_projects", "folder_areas", "folder_resources"),
            helper.STAT_ROOT_KEYS)


if __name__ == "__main__":
    unittest.main()
