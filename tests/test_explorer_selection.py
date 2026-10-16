"""The Explorer highlights one row: the last one tapped.

Each `Folder` used to keep its own `sel` flag and only ever set it to true, so
every folder tapped stayed highlighted and a note row had no highlight at all.
The selection is now one value owned by `Explorer`. It is component state, so
this reads the source (the same trade `tests/test_addnote_keyboard.py` makes),
plus the esbuild parse in `tests/test_webapp_compiles.py` that covers syntax.
"""

import re
import unittest
from pathlib import Path

SRC = Path(__file__).parents[1] / "browser" / "webapp" / "src"
EXPLORER = (SRC / "components" / "Explorer.jsx").read_text(encoding="utf-8")
CSS = (SRC / "styles.css").read_text(encoding="utf-8")


class SingleSelectionTests(unittest.TestCase):
    def test_the_selection_is_one_value_owned_by_the_explorer(self):
        explorer = EXPLORER[EXPLORER.index("export default function Explorer"):]

        self.assertIn("const [selected, setSelected] = useState(null);", explorer)

    def test_a_folder_keeps_no_selection_of_its_own(self):
        """The bug: a per-folder flag that only ever went true."""
        self.assertNotIn("setSel(", EXPLORER)
        self.assertNotIn("const [sel,", EXPLORER)

    def test_folders_and_notes_are_selected_by_distinct_keys(self):
        """A folder path and a note id must never collide."""
        self.assertIn('const folderKey = (path) => "folder:" + path;', EXPLORER)
        self.assertIn('const noteKey = (id) => "note:" + id;', EXPLORER)

    def test_tapping_a_folder_selects_it_and_still_toggles(self):
        self.assertIn("setOpen((o) => !o); onSelect(folderKey(path));", EXPLORER)

    def test_tapping_a_note_selects_it_and_opens_it(self):
        self.assertIn("onSelect(noteKey(note.id)); openNote(note.id);", EXPLORER)

    def test_notes_get_the_same_highlight_as_folders(self):
        """One look for a selected row, whatever it is."""
        self.assertEqual(2, len(re.findall(r'" selected" : ""', EXPLORER)))
        self.assertIn("  .row.selected {", CSS)

    def test_selection_reaches_every_nested_row(self):
        """Folders pass it to their children, files and subfolders alike."""
        self.assertEqual(2, EXPLORER.count("selected={selected} onSelect={onSelect}"))
        self.assertIn("selected={selected} onSelect={setSelected}", EXPLORER)

    def test_the_dead_active_style_is_gone(self):
        """`.file.active` was never applied by anything."""
        self.assertNotIn(".file.active", CSS)


if __name__ == "__main__":
    unittest.main()
