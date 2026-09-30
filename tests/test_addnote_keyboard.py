"""The Add-note page's keyboard handling.

Two things here are easy to get wrong and impossible to see in a passing render:

* **`keyboardInset`** decides how far the floating bar lifts. Ignore
  `offsetTop` and the bar drifts as iOS scrolls the visual viewport under the
  keyboard; forget the `Math.max` and a viewport briefly *taller* than the
  window pushes the bar off the bottom of the screen.
* **The focus path.** iOS and Telegram's webview raise the keyboard only for a
  `focus()` made inside a user gesture. That forces two structural choices —
  the overlay is never unmounted or `display: none` (neither leaves a focusable
  element), and `openAddNote` focuses before it patches state. Both look like
  stylistic quirks and would be "tidied away" by the next reader, so they are
  pinned here.

The maths runs under node against the real module; the structure is read from
source, because what matters is which construct is used, not what it renders to.
"""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
FORMAT_JS = ROOT / "browser" / "webapp" / "src" / "lib" / "format.js"
ADDNOTE = ROOT / "browser" / "webapp" / "src" / "components" / "AddNote.jsx"
CONTEXT = ROOT / "browser" / "webapp" / "src" / "store" / "AppContext.jsx"
CSS = ROOT / "browser" / "webapp" / "src" / "styles.css"

SCRIPT = """
import { keyboardInset } from %s;
const cases = JSON.parse(process.argv[2]);
console.log(JSON.stringify(cases.map(([h, v]) => keyboardInset(h, v))));
"""


def _insets(cases):
    script = ROOT / "tests" / ".keyboard_inset.mjs"
    script.write_text(SCRIPT % json.dumps(FORMAT_JS.as_posix()), encoding="utf-8")
    try:
        out = subprocess.run(["node", str(script), json.dumps(cases)],
                             capture_output=True, text=True, check=True)
    finally:
        script.unlink(missing_ok=True)

    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node is not available")
class KeyboardInsetTests(unittest.TestCase):
    def test_no_keyboard_means_no_lift(self):
        """Viewport fills the window: the bar stays at its normal offset."""
        self.assertEqual([0], _insets([[800, {"height": 800, "offsetTop": 0}]]))

    def test_an_open_keyboard_is_the_hidden_remainder(self):
        self.assertEqual([300], _insets([[800, {"height": 500, "offsetTop": 0}]]))

    def test_a_scrolled_visual_viewport_counts_too(self):
        """iOS scrolls the visual viewport when the keyboard opens. Without
        `offsetTop` the bar drifts away from the keyboard's top edge as the
        page moves beneath it."""
        self.assertEqual([340], _insets([[800, {"height": 400, "offsetTop": 60}]]))

    def test_a_missing_visual_viewport_lifts_nothing(self):
        """Older webviews have no `visualViewport`. The bar then sits where it
        always did rather than at some computed-from-undefined position."""
        self.assertEqual([0, 0], _insets([[800, None], [800, 0]]))

    def test_the_inset_never_goes_negative(self):
        """A viewport reported taller than the window — which happens mid
        rotation — would otherwise push the bar down off the screen."""
        self.assertEqual([0], _insets([[600, {"height": 700, "offsetTop": 0}]]))

    def test_a_viewport_without_offsettop_is_treated_as_unscrolled(self):
        self.assertEqual([300], _insets([[800, {"height": 500}]]))


class FocusPathTests(unittest.TestCase):
    """Why the overlay is always mounted, and why focus precedes the patch."""

    def setUp(self):
        self.addnote = ADDNOTE.read_text(encoding="utf-8")
        self.context = CONTEXT.read_text(encoding="utf-8")
        self.css = CSS.read_text(encoding="utf-8")

    def test_the_overlay_is_never_unmounted_while_closed(self):
        """`if (!open) return null` is the obvious tidy-up and it breaks the
        keyboard: there is then no textarea to focus during the tap."""
        self.assertNotRegex(self.addnote, r"return null")

    def test_the_overlay_is_hidden_with_opacity_not_display(self):
        """`display: none` and `visibility: hidden` both make a field
        unfocusable; opacity does not."""
        block = self.css.split(".addnote {", 1)[1].split("}", 1)[0]

        self.assertIn("opacity: 0", block)
        self.assertNotIn("display: none", block)
        self.assertNotIn("visibility: hidden", block)

    def test_the_hidden_overlay_does_not_swallow_taps(self):
        """It covers the whole screen at z-index 60 even when invisible."""
        block = self.css.split(".addnote {", 1)[1].split("}", 1)[0]

        self.assertIn("pointer-events: none", block)

    def test_opening_focuses_before_it_patches_state(self):
        """The gesture is alive only until the handler returns, and `patch` is
        async — focusing after the re-render gets a caret and no keyboard."""
        body = self.context.split("const openAddNote", 1)[1].split("const closeAddNote", 1)[0]
        focus_at = body.index(".focus()")
        patch_at = body.index("patch(")

        self.assertLess(focus_at, patch_at)

    def test_the_input_ref_is_shared_through_the_store(self):
        """The button that opens the page is in Header, the field is in
        AddNote; they meet at the ref rather than through a DOM query."""
        self.assertIn("addNoteInputRef", self.context)
        self.assertIn("addNoteInputRef", self.addnote)

    def test_the_closed_field_is_out_of_the_tab_order(self):
        """Still in the DOM, so it must not be reachable by keyboard."""
        self.assertIn("tabIndex={open ? 0 : -1}", self.addnote)


class BarTests(unittest.TestCase):
    def setUp(self):
        self.addnote = ADDNOTE.read_text(encoding="utf-8")
        self.css = CSS.read_text(encoding="utf-8")

    def test_the_buttons_reuse_the_dock_glass(self):
        """Both circles carry `.fab`, so this bar and the dock cannot drift
        apart in size, border or shadow. Matched on the class *prefix* rather
        than the exact attribute: the tick adds a `commit` modifier, and an
        assertion on `className="fab"` alone fails on correct markup."""
        self.assertEqual(2, len(re.findall(r'className="fab\b', self.addnote)))

    def test_only_the_tick_is_the_commit_colour(self):
        """A discard should not compete with the commit for attention."""
        self.assertEqual(1, self.addnote.count('className="fab commit"'))

    def test_the_capture_pill_reuses_the_docks_capsule(self):
        """`.tabbar` is the dock's own pill class, so the two capsules cannot
        drift apart in blur, border or radius."""
        self.assertIn('className="tabbar"', self.addnote)

    def test_the_pill_offers_the_three_capture_kinds(self):
        """The same three the bot accepts, plus the one bit of metadata worth
        setting while the thought is fresh."""
        self.assertEqual(["photo", "voice", "reminder"],
                         re.findall(r'kind: "(\w+)"', self.addnote))

    def test_every_capture_button_is_disabled(self):
        """There is no note-create endpoint yet, so none of these can do
        anything. `disabled` is what makes that legible rather than looking
        like a button that swallowed the tap."""
        pill = self.addnote.split('className="tabbar"', 1)[1].split("</nav>", 1)[0]

        self.assertEqual(1, pill.count("<button"))
        self.assertEqual(1, pill.count("disabled"))

    def test_the_icon_only_buttons_carry_accessible_names(self):
        """Three bare glyphs are unreadable to a screen reader without one."""
        self.assertIn("aria-label={capture.label}", self.addnote)
        self.assertEqual(3, len(re.findall(r'label: "[^"]+"', self.addnote)))

    def test_the_bar_carries_the_keyboard_inset_inline(self):
        """Only JS can measure it, so it cannot live in the stylesheet."""
        self.assertIn("${inset}px", self.addnote)

    def test_the_bar_sits_at_the_docks_own_offset(self):
        self.assertIn("calc(30px + env(safe-area-inset-bottom, 0px)", self.addnote)

    def test_the_text_clears_the_floating_bar(self):
        """The bar floats over the textarea, so without bottom padding the
        last line of a long note ends up underneath it."""
        block = self.css.split(".addnote-body {", 1)[1].split("}", 1)[0]
        padding = re.search(r"padding:(.*?);", block, re.S).group(1)

        self.assertIn("100px", padding)


if __name__ == "__main__":
    unittest.main()
