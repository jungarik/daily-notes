"""The note card's reading order, its clamped body, and the sheet's grip.

Three changes, each with one thing worth pinning:

* **Order.** The note's own text comes first, under the images; the date, path
  and tags follow. They are the machine's description of what the user wrote,
  so they sit after it, not above it.
* **The clamp.** `clampText` is pure and runs under node. Its interesting
  cases are the ones a reader skims: a cut that would land mid-word, and a
  single long token with no space to retreat to.
* **The grip.** It scrolls away on any sheet tall enough to scroll, which in
  practice means a note with a photo. Sticky is half the fix; covering the
  sheet's own padding is the other half, and that is a CSS property nothing
  else asserts.
"""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
WEBAPP = ROOT / "browser" / "webapp" / "src"
FORMAT_JS = WEBAPP / "lib" / "format.js"
CARD = (WEBAPP / "components" / "NoteCard.jsx").read_text(encoding="utf-8")
# The same file without comments. The checks for what the card no longer
# *renders* have to run against this: the comments explain what was removed and
# therefore contain the very strings such a check looks for. Crude — it would
# also cut `//` inside a string literal — but this file has none.
CARD_CODE = re.sub(r"//[^\n]*|/\*(?:.|\n)*?\*/", "", CARD)
CSS = (WEBAPP / "styles.css").read_text(encoding="utf-8")

SCRIPT = """
import { clampText, CLAMP_CHARS } from %s;
const [text, limit] = JSON.parse(process.argv[2]);
console.log(JSON.stringify(clampText(text, limit === null ? CLAMP_CHARS : limit)));
"""


def _clamp(text, limit=None):
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "clamp.mjs"
        script.write_text(SCRIPT % json.dumps(FORMAT_JS.as_posix()), encoding="utf-8")
        out = subprocess.run(
            ["node", str(script), json.dumps([text, limit])],
            capture_output=True, text=True, check=True)

    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node is not available")
class ClampTests(unittest.TestCase):
    def test_a_short_note_is_whole_and_has_no_rest(self):
        """An empty `rest` is the signal that there is no control to render —
        the component never compares lengths itself."""
        self.assertEqual({"head": "short", "rest": ""}, _clamp("short"))

    def test_a_note_exactly_at_the_limit_is_not_clamped(self):
        """Off-by-one here costs a "… more" that reveals nothing."""
        self.assertEqual("", _clamp("a" * 100)["rest"])

    def test_one_character_over_is_clamped(self):
        self.assertNotEqual("", _clamp("a " * 80)["rest"])

    def test_the_cut_falls_back_to_the_last_space(self):
        """A word sliced in half reads as a rendering fault, so the limit is a
        budget rather than a target."""
        head = _clamp("word " * 30)["head"]

        self.assertTrue(head.endswith("word"), head)
        self.assertLessEqual(len(head), 100)

    def test_the_two_halves_still_contain_everything(self):
        """The split trims the seam, so the halves do not rejoin into the
        original — the card renders the original when expanded for exactly
        that reason. What must hold is that no word is lost."""
        text = "alpha beta gamma delta " * 10
        parts = _clamp(text)

        self.assertEqual(text.split(), (parts["head"] + " " + parts["rest"]).split())

    def test_a_single_long_token_is_cut_at_the_limit(self):
        """A URL has no space to retreat to. A hard break beats showing a
        400-character "preview"."""
        parts = _clamp("x" * 400)

        self.assertEqual(100, len(parts["head"]))
        self.assertEqual(300, len(parts["rest"]))

    def test_an_early_space_is_not_used_as_the_cut(self):
        """`"a " + 300 x`: the only space is at index 1, and cutting there
        would show one character. Below half the limit it is ignored."""
        self.assertEqual(100, len(_clamp("a " + "x" * 300)["head"]))

    def test_empty_and_missing_text_are_safe(self):
        self.assertEqual({"head": "", "rest": ""}, _clamp(""))
        self.assertEqual({"head": "", "rest": ""}, _clamp(None))


class CardOrderTests(unittest.TestCase):
    def _order(self, *needles):
        return [CARD.index(needle) for needle in needles]

    def test_the_text_comes_before_the_metadata(self):
        """The note's own words first; the date, path and tags describe them."""
        body, head, path, tags = self._order(
            "<Body text={text} />", '<div className="post-head">',
            '"📁 " + detail.path', "{tags && ")

        self.assertEqual([body, head, path, tags], sorted([body, head, path, tags]))

    def test_the_images_stay_above_everything(self):
        """The carousel is the one thing the text does not lead."""
        self.assertLess(CARD.index("<Carousel"), CARD.index("<Body text={text} />"))

    def test_the_dots_still_travel_with_the_date(self):
        """One row, so the menu is where the timestamp is rather than floating
        in a row of its own."""
        head = CARD.index('<div className="post-head">')
        path = CARD.index('"📁 " + detail.path')

        self.assertLess(head, CARD.index('className="post-dots"'))
        self.assertLess(CARD.index('className="post-dots"'), path)

    def test_the_divider_moved_to_the_metadata(self):
        """It used to sit above the body, separating it from the title. With
        the body on top the rule belongs where the machine's description
        starts — otherwise the card opens with a line across it."""
        start = CSS.index("  .card-body {")
        body_rule = CSS[start:CSS.index("}", start)]
        start = CSS.index("  .post-head {")
        head_rule = CSS[start:CSS.index("}", start)]

        self.assertNotIn("border-top", body_rule)
        self.assertIn("border-top: 1px dashed", head_rule)

    def test_an_empty_note_still_says_so(self):
        """Only when it has no images either: with photos the pictures are
        the note and a placeholder would be wrong."""
        self.assertIn("(empty note)", CARD)
        self.assertIn("!hasImages && ", CARD)


class LinkedNotesTests(unittest.TestCase):
    def test_the_heading_is_gone(self):
        """A row of 🔗-prefixed chips is self-describing."""
        self.assertNotIn("Linked notes", CARD_CODE)
        self.assertNotIn("links-label", CARD_CODE)

    def test_the_absence_is_no_longer_reported(self):
        """"No linked notes yet" was a line of text about something the user
        had not asked about."""
        self.assertNotIn("No linked notes", CARD_CODE)

    def test_nothing_renders_when_there_are_none(self):
        """Not an empty container relying on `:empty`, which an intermediate
        div would defeat."""
        self.assertIn("{links.length > 0 && (", CARD)

    def test_the_dead_heading_rule_went_with_it(self):
        self.assertNotIn(".links-label", CSS)


class SheetGripTests(unittest.TestCase):
    def _grip_rule(self):
        start = CSS.index("  .sheet .grip {")

        return CSS[start:CSS.index("}", start)]

    def test_the_grip_is_sticky(self):
        self.assertIn("position: sticky", self._grip_rule())

    def test_the_grip_is_opaque(self):
        """Sticky over transparent is a bar you can see the content through."""
        self.assertIn("background: var(--bg-elev)", self._grip_rule())

    def test_the_grip_covers_the_sheets_own_padding(self):
        """The sheet's 14px/18px padding is inside the scrollport, so content
        travels through it above and beside a narrow bar. The negative margins
        and the negative `top` are what close that gap — this is the assertion
        that would catch someone "simplifying" them away."""
        rule = self._grip_rule()

        self.assertIn("top: -14px", rule)
        self.assertIn("margin: -14px -18px 12px", rule)

    def test_the_pill_is_drawn_as_a_pseudo_element(self):
        """The grip element is now the full-width band; the 36x4 pill it used
        to be is centred inside it."""
        start = CSS.index("  .sheet .grip::after {")
        pill = CSS[start:CSS.index("}", start)]

        self.assertIn("width: 36px", pill)
        self.assertIn("height: 4px", pill)
        self.assertIn("margin: 0 auto", pill)

    def test_the_sheet_still_scrolls(self):
        """The fix is about what stays visible while it scrolls, not about
        stopping it."""
        start = CSS.index("  .sheet {")
        sheet = CSS[start:CSS.index("}", start)]

        self.assertIn("overflow-y: auto", sheet)
        self.assertIn("padding: 14px 18px", sheet)


if __name__ == "__main__":
    unittest.main()
