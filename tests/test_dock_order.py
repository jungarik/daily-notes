"""The dock's tabs run Explorer, Notes, Map, and the app opens on the Explorer."""

import re
import unittest
from pathlib import Path

SRC = Path(__file__).parents[1] / "browser" / "webapp" / "src"
DOCK = (SRC / "components" / "Dock.jsx").read_text(encoding="utf-8")
STORE = (SRC / "store" / "AppContext.jsx").read_text(encoding="utf-8")


class DockOrderTests(unittest.TestCase):
    def test_tabs_run_explorer_notes_map(self):
        tabs = DOCK.split("const TABS = [", 1)[1].split("];", 1)[0]

        self.assertEqual(["explorer", "notes", "map"], re.findall(r'\{ view: "(\w+)"', tabs))

    def test_the_app_opens_on_the_explorer(self):
        self.assertRegex(STORE, r'view: "explorer",')
        self.assertRegex(STORE, r'prevView: "explorer",')

    def test_closing_chat_or_search_returns_to_the_explorer_first_run(self):
        self.assertIn("setView(state.prevView)", STORE)


if __name__ == "__main__":
    unittest.main()
