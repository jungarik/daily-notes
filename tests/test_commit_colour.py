"""One blue for every affirmative action.

The app has two accent colours doing two jobs: `--commit` (blue) for *actions*
— send, confirm, save, the Add-note tick, the header's plus — and `--accent`
(violet) for *state*, like an active filter or a note's path. The split is only
worth anything if it is absolute: a violet Save beside a blue Send teaches the
reader that the colour means nothing, which is what the Save button used to do.

Read from source rather than rendered. The question is which token each rule
names, and a screenshot cannot answer that.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
CSS_PATH = ROOT / "browser" / "webapp" / "src" / "styles.css"
CSS = CSS_PATH.read_text(encoding="utf-8")

# Every rule whose button is an affirmative: it sends, saves, confirms or
# creates. Each must paint itself from --commit.
AFFIRMATIVE = (
    ".tab-input .ts-send",     # the pill's send button
    ".confirm-btn.yes",        # chat's Confirm on a proposed write
    ".path-btn.primary",       # Save on the change-path sheet
    ".fab.commit",             # the Add-note tick
    ".hdr-add",                # the header's plus badge
)


def _rule(selector: str) -> str:
    """The declaration block for a selector, without its trailing brace."""
    start = CSS.index(selector + " {") + len(selector) + 2

    return CSS[start:CSS.index("}", start)]


def _variable(name: str) -> str:
    return re.search(rf"--{name}:\s*(#[0-9a-fA-F]{{6}})", CSS).group(1)


def _contrast(foreground: str, background: str) -> float:
    def channel(value):
        value /= 255

        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    def luminance(colour):
        colour = colour.lstrip("#")
        red, green, blue = (int(colour[i:i + 2], 16) for i in (0, 2, 4))

        return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)

    high, low = sorted((luminance(foreground), luminance(background)), reverse=True)

    return (high + 0.05) / (low + 0.05)


class CommitColourTests(unittest.TestCase):
    def test_every_affirmative_control_uses_the_commit_token(self):
        missing = [selector for selector in AFFIRMATIVE
                   if "var(--commit)" not in _rule(selector)]

        self.assertEqual([], missing,
                         "these affirmative controls are not the commit blue")

    def test_no_affirmative_control_uses_the_state_accent(self):
        """`--accent` is violet and means state. Save used to take it, which
        is the confusion this file exists to prevent coming back."""
        offending = [selector for selector in AFFIRMATIVE
                     if "var(--accent)" in _rule(selector)]

        self.assertEqual([], offending)

    def test_the_blue_is_defined_once_and_not_repeated_as_a_hex(self):
        """It was written out eleven times before it became a variable, which
        is how one of them would eventually have drifted.

        The value is read from the declaration rather than hard-coded here, so
        changing the blue stays a one-line edit instead of also failing this."""
        blue = _variable("commit")
        literals = re.findall(re.escape(blue), CSS, re.IGNORECASE)

        self.assertEqual(1, len(literals),
                         f"{blue} should appear only in its :root declaration")

    def test_white_is_legible_on_the_commit_blue(self):
        """Every one of these paints white glyphs or text on the fill."""
        self.assertGreaterEqual(_contrast("#ffffff", _variable("commit")), 4.5)

    def test_commit_and_accent_are_different_colours(self):
        """Guards the guard: if they were ever set to the same value the two
        assertions above would both pass while the distinction was gone."""
        self.assertNotEqual(_variable("commit"), _variable("accent"))

    def test_the_selectors_being_checked_actually_exist(self):
        """A renamed class would make `_rule` raise rather than silently pass,
        but a typo in this list would not — so the list is checked too."""
        for selector in AFFIRMATIVE:
            with self.subTest(selector=selector):
                self.assertIn(selector + " {", CSS)


if __name__ == "__main__":
    unittest.main()
