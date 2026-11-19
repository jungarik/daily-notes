"""Notes are listed newest first, in every explorer folder.

`compareNewest` is executed under node rather than read, and the Explorer is
checked to use it for both a folder's notes and the loose notes at the top
level — the two places that used to sort by label (or not at all).
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SRC = ROOT / "browser" / "webapp" / "src"
FORMAT_JS = SRC / "lib" / "format.js"
EXPLORER = (SRC / "components" / "Explorer.jsx").read_text(encoding="utf-8")

SCRIPT = """
import { compareNewest } from %s;
const notes = JSON.parse(process.argv[2]);
console.log(JSON.stringify(notes.sort(compareNewest).map((n) => n.id)));
"""


def _order(notes):
    with tempfile.TemporaryDirectory() as folder:
        script = Path(folder) / "order.mjs"
        script.write_text(SCRIPT % json.dumps(FORMAT_JS.as_posix()), encoding="utf-8")
        out = subprocess.run(
            ["node", str(script), json.dumps(notes)],
            capture_output=True, text=True, check=True)

    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node is not available")
class CompareNewestTests(unittest.TestCase):
    def test_newest_created_first(self):
        notes = [
            {"id": 1, "created_at": "2026-01-01T10:00:00+00:00"},
            {"id": 2, "created_at": "2026-03-01T10:00:00+00:00"},
            {"id": 3, "created_at": "2026-02-01T10:00:00+00:00"},
        ]

        self.assertEqual([2, 3, 1], _order(notes))

    def test_offsets_are_compared_as_instants_not_as_text(self):
        notes = [
            {"id": 1, "created_at": "2026-01-01T12:00:00+05:00"},   # 07:00 UTC
            {"id": 2, "created_at": "2026-01-01T09:00:00+00:00"},   # 09:00 UTC
        ]

        self.assertEqual([2, 1], _order(notes))

    def test_the_same_instant_falls_back_to_the_higher_id(self):
        notes = [
            {"id": 4, "created_at": "2026-01-01T10:00:00+00:00"},
            {"id": 9, "created_at": "2026-01-01T10:00:00+00:00"},
        ]

        self.assertEqual([9, 4], _order(notes))

    def test_an_undated_note_sorts_last(self):
        notes = [
            {"id": 8, "created_at": None},
            {"id": 1, "created_at": "2020-01-01T00:00:00+00:00"},
            {"id": 9},
        ]

        self.assertEqual([1, 9, 8], _order(notes))


class ExplorerUsesItTests(unittest.TestCase):
    def test_a_folders_notes_are_sorted_newest_first(self):
        self.assertIn("node.files.slice().sort(compareNewest)", EXPLORER)

    def test_loose_top_level_notes_are_sorted_too(self):
        self.assertIn("root.files.slice().sort(compareNewest)", EXPLORER)

    def test_the_label_sort_is_gone(self):
        self.assertNotIn("a.label || \"\").localeCompare", EXPLORER)


if __name__ == "__main__":
    unittest.main()
