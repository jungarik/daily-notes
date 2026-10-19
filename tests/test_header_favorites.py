"""The header's favourite folders: the grouping query, the ordering, the row.

The grouping rule lives in the query, so it is run for real against an
in-memory SQLite vault (only the dialect is translated). The ordering is a pure
function and is called directly. The row itself — the circles, their names, the
sideways scroll — is a Mini App component, so it is checked from source, like
the other page tests.
"""

import sqlite3
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SRC = ROOT / "browser" / "webapp" / "src"

_had_db = "db" in sys.modules

if not _had_db:
    _stub = types.ModuleType("db")
    _stub.cursor = lambda: None
    sys.modules["db"] = _stub

from api.header import helper                # noqa: E402

if not _had_db:
    del sys.modules["db"]

DB_SOURCE = (ROOT / "api" / "header" / "db.py").read_text(encoding="utf-8")
HEADER = (SRC / "components" / "Header.jsx").read_text(encoding="utf-8")
STORIES = (SRC / "components" / "FavoriteNotes.jsx").read_text(encoding="utf-8")
RING = (SRC / "components" / "CountRing.jsx").read_text(encoding="utf-8")
CSS = (SRC / "styles.css").read_text(encoding="utf-8")


def _run_query(rows):
    """The real favourites query over `rows` of (user_id, path, is_favorite)."""
    body = DB_SOURCE.split("def count_favorites_by_folder", 1)[1]
    sql = body.split("cur.execute(", 1)[1].split('"""')[1]
    sql = sql.replace("split_part(path, '/', 1)",
                      "CASE WHEN instr(path,'/') = 0 THEN path "
                      "ELSE substr(path, 1, instr(path,'/') - 1) END")
    sql = sql.replace("split_part(path, '/', 2)",
                      "CASE WHEN instr(path,'/') = 0 THEN '' "
                      "ELSE substr(path, instr(path,'/') + 1) END")
    sql = sql.replace("%s", "?")

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE notes (user_id INT, path TEXT, is_favorite BOOL);")
    conn.executemany("INSERT INTO notes VALUES (?, ?, ?);", rows)
    found = conn.execute(sql, (7,)).fetchall()
    conn.close()

    return {(row[0], row[1]): row[2] for row in found}


class GroupingTests(unittest.TestCase):
    def test_groups_by_the_notes_own_two_levels(self):
        groups = _run_query([
            (7, "Projects/api", 1), (7, "Projects/api", 1), (7, "Projects/web", 1),
            (7, "Projects", 1), (7, "Areas", 1),
        ])

        self.assertEqual({
            ("Projects", "api"): 2,
            ("Projects", "web"): 1,
            ("Projects", ""): 1,
            ("Areas", ""): 1,
        }, groups)

    def test_only_favourites_of_this_user_with_a_path_count(self):
        groups = _run_query([
            (7, "Projects/api", 0), (8, "Projects/api", 1),
            (7, "", 1), (7, None, 1), (7, "Areas/x", 1),
        ])

        self.assertEqual({("Areas", "x"): 1}, groups)

    def test_the_owner_predicate_is_in_the_query(self):
        self.assertIn("WHERE user_id = %s AND is_favorite", DB_SOURCE)


class OrderingTests(unittest.TestCase):
    ROOTS = ["Inbox", "Projects", "Areas", "Resources"]

    def test_root_order_then_loose_notes_then_sub_folders_by_name(self):
        ordered = helper.order_favorites([
            ("Areas", "", 1), ("Projects", "web", 2), ("Projects", "api", 3),
            ("Projects", "", 4), ("Inbox", "", 5),
        ], self.ROOTS)

        self.assertEqual(
            [("Inbox", ""), ("Projects", ""), ("Projects", "api"), ("Projects", "web"), ("Areas", "")],
            [(g["root"], g["sub"]) for g in ordered])

    def test_an_unknown_root_sorts_last_and_is_kept(self):
        ordered = helper.order_favorites([("Old", "x", 1), ("Areas", "", 1)], self.ROOTS)

        self.assertEqual(["Areas", "Old"], [g["root"] for g in ordered])

    def test_the_label_is_the_sub_folder_or_the_root(self):
        ordered = helper.order_favorites([("Projects", "api", 2), ("Areas", "", 1)], self.ROOTS)
        labels = {g["root"]: g["label"] for g in ordered}

        self.assertEqual({"Projects": "api", "Areas": "Areas"}, labels)

    def test_counts_are_carried_and_the_input_is_not_mutated(self):
        rows = [("Projects", "api", 2)]
        ordered = helper.order_favorites(rows, self.ROOTS)

        self.assertEqual(2, ordered[0]["count"])
        self.assertEqual([("Projects", "api", 2)], rows)


class RowTests(unittest.TestCase):
    def test_the_header_shows_stories_and_no_root_counts(self):
        self.assertIn("<FavoriteNotes groups={state.favorites || []} />", HEADER)
        self.assertNotIn("hdr-stats", HEADER + CSS)
        self.assertNotIn('className="stat"', HEADER)

    def test_inbox_and_stories_draw_the_same_ring(self):
        self.assertIn("<CountRing count={count} />", HEADER)
        self.assertIn("<CountRing count={group.count} />", STORIES)
        self.assertEqual(1, RING.count("<circle\n        className=\"hdr-ring-disc\""))

    def test_the_stories_are_a_sideways_scroller(self):
        rule = CSS.split("  .hdr-stories {", 1)[1].split("}", 1)[0]

        self.assertIn("overflow-x: auto;", rule)
        self.assertIn("min-width: 0;", rule)
        self.assertIn("pointer-events: auto;", rule)

    def test_each_circle_is_smaller_than_the_inbox_and_the_name_ellipsises(self):
        self.assertIn(".hdr-inbox { position: relative; width: 64px; height: 64px;", CSS)
        self.assertIn(".story .hdr-ring { position: static; width: 52px; height: 52px; }", CSS)

        name = CSS.split("  .story-name {", 1)[1].split("}", 1)[0]

        self.assertIn("text-overflow: ellipsis;", name)
        self.assertIn("white-space: nowrap;", name)

    def test_the_payload_reaches_the_store(self):
        store = (SRC / "store" / "AppContext.jsx").read_text(encoding="utf-8")

        self.assertIn("favorites: header.favorites || []", store)

    def test_the_codebase_never_names_that_social_app(self):
        banned = "insta" + "gram"

        for path in list(SRC.rglob("*.js*")) + list(SRC.rglob("*.css")) + list(ROOT.glob("*.md")):
            with self.subTest(path=path.name):
                self.assertNotIn(banned, path.read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
