"""The ⋮ menu's icons are drawn the way the rest of the app draws icons.

The menu used emoji (✏️ 📁 🗑). Three problems, none of which a screenshot on
one device shows: emoji render in a different style on every platform, so the
menu looked like it came from somewhere else; they carry their own colour, so
the Delete item's label went red while its glyph stayed grey; and they sit on
the text baseline rather than in a box, which left them a few pixels off centre
beside a 14px label.

The app's icon recipe is a 24-viewBox inline SVG with `fill: none`,
`stroke: currentColor` and a 1.8 stroke — the dock's tabs, the pill's Send and
the Add-note page's side buttons all use it. This file pins that the menu now
does too, and that nothing reintroduces an emoji.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
COMPONENTS = ROOT / "browser" / "webapp" / "src" / "components"
MENU = (COMPONENTS / "ContextMenu.jsx").read_text(encoding="utf-8")
ADDNOTE = (COMPONENTS / "AddNote.jsx").read_text(encoding="utf-8")
CSS = (ROOT / "browser" / "webapp" / "src" / "styles.css").read_text(encoding="utf-8")

# The menu's own markup, comments stripped: the comments explain which emoji
# were removed and so contain the characters a check for them would find.
MENU_CODE = re.sub(r"//[^\n]*|/\*(?:.|\n)*?\*/", "", MENU)

ITEMS = ("EditGlyph", "FolderGlyph", "TrashGlyph")


def _svg(name: str) -> str:
    """The glyph component's body."""
    start = MENU.index("const " + name + " = () => (")

    return MENU[start:MENU.index(");", start)]


class IconStyleTests(unittest.TestCase):
    def test_each_item_has_a_glyph_component(self):
        for name in ITEMS:
            with self.subTest(glyph=name):
                self.assertIn("const " + name + " = () => (", MENU)

    def test_each_glyph_follows_the_app_recipe(self):
        """Same viewBox, same fill, same stroke width as the dock's icons. A
        glyph drawn at a different weight reads as a different icon set."""
        for name in ITEMS:
            with self.subTest(glyph=name):
                body = _svg(name)
                self.assertIn('viewBox="0 0 24 24"', body)
                self.assertIn('fill="none"', body)
                self.assertIn('strokeWidth="1.8"', body)

    def test_each_glyph_inherits_its_colour(self):
        """`currentColor` is what makes the Delete glyph go red with its
        label, instead of needing a rule of its own."""
        for name in ITEMS:
            with self.subTest(glyph=name):
                self.assertIn('stroke="currentColor"', _svg(name))

    def test_no_glyph_hard_codes_a_colour(self):
        for name in ITEMS:
            with self.subTest(glyph=name):
                self.assertNotIn("#", _svg(name))

    def test_the_folder_glyph_is_the_one_the_addnote_page_uses(self):
        """The same object should not be drawn two ways. Both files carry the
        path inline — the repo duplicates rather than sharing — so this is the
        assertion that notices when one of them drifts."""
        path = re.search(r'<path d="(M3 6\.5[^"]+)"', _svg("FolderGlyph")).group(1)

        self.assertIn(path, ADDNOTE)

    def test_the_menu_carries_no_emoji(self):
        """Including the ones that were there: a reader adding a fourth item
        would otherwise copy whichever style they saw first."""
        for emoji in ("✏️", "📁", "🗑"):
            with self.subTest(emoji=emoji):
                self.assertNotIn(emoji, MENU_CODE)

    def test_the_labels_survived(self):
        """Replacing the icon is not an excuse to lose the words — the menu is
        read, not recognised."""
        for label in (">Edit", ">Change path", ">Delete"):
            with self.subTest(label=label):
                self.assertIn(label.lstrip(">"), MENU_CODE)


class IconLayoutTests(unittest.TestCase):
    def _item_rule(self) -> str:
        start = CSS.index("  .ctx-item {")

        return CSS[start:CSS.index("}", start)]

    def test_the_item_is_a_flex_row(self):
        """So the glyph keeps its own box and every label starts on the same
        x — with an emoji inside the text, a two-line label wrapped under the
        icon."""
        rule = self._item_rule()

        self.assertIn("display: flex", rule)
        self.assertIn("align-items: center", rule)
        self.assertNotIn("display: block", rule)

    def test_the_glyph_is_sized_and_cannot_shrink(self):
        """`flex: none`, or a long label squeezes the icon."""
        start = CSS.index("  .ctx-item svg {")
        rule = CSS[start:CSS.index("}", start)]

        self.assertIn("flex: none", rule)
        self.assertIn("width: 17px", rule)
        self.assertIn("height: 17px", rule)

    def test_the_glyph_has_a_gap_from_the_label(self):
        self.assertIn("gap:", self._item_rule())

    def test_the_danger_item_still_colours_the_whole_row(self):
        """The glyph follows because it strokes `currentColor`."""
        self.assertIn(".ctx-item.danger { color: var(--danger-text); }", CSS)


if __name__ == "__main__":
    unittest.main()
