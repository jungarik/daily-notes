"""`ringDashes` from the Mini App's header, executed rather than read.

The Inbox ring draws one segment per waiting note, and the whole thing is a
dash pattern — so a wrong number here is a picture that lies about how much is
in the Inbox, which is the only thing the ring exists to say. Node runs the
actual module, so this breaks if the source does.

Two properties are worth pinning beyond the segment count. The pattern must
tile: `dash + gap` has to equal the circle's share per segment, or the segments
drift out of phase and the last one overlaps the first. And the gap has to
absorb the round line caps, which paint half a stroke width past each end of
every dash — ignore that and the gaps close up exactly when the count is
highest and the ring is least readable.

Skipped when node is unavailable; the Python suite must stay runnable without
a JS toolchain.
"""

import json
import math
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
FORMAT_JS = ROOT / "browser" / "webapp" / "src" / "lib" / "format.js"

# The header's own geometry, mirrored from Header.jsx: the dashed ring sits in
# the band outside the 54-unit disc, separated from it by a 2.5-unit gap, each
# radius inset by half its own stroke. Only the dashed ring is computed here —
# the disc is a plain circle with nothing to get wrong.
DISC_STROKE = 1.5
DISC_R = (54 - DISC_STROKE) / 2
RING_INSET = 2.5
STROKE = 2.5
RADIUS = DISC_R + DISC_STROKE / 2 + RING_INSET + STROKE / 2
CIRCUMFERENCE = 2 * math.pi * RADIUS

SCRIPT = """
import { ringDashes, RING_MAX_SEGMENTS, formatCount, COUNT_CAP } from %s;
const counts = JSON.parse(process.argv[2]);
console.log(JSON.stringify({
  cap: RING_MAX_SEGMENTS,
  countCap: COUNT_CAP,
  rings: counts.map((n) => ringDashes(n, %r, %r)),
  labels: counts.map(formatCount),
}));
"""


def _labels(counts):
    """The text drawn in the disc, for each count."""
    return _rings(counts)["labels"]


def _rings(counts):
    """Run the real module under node and return its output for each count."""
    script = ROOT / "tests" / ".ring_dashes.mjs"
    script.write_text(
        SCRIPT % (json.dumps(FORMAT_JS.as_posix()), CIRCUMFERENCE, STROKE),
        encoding="utf-8")
    try:
        out = subprocess.run(
            ["node", str(script), json.dumps(counts)],
            capture_output=True, text=True, check=True)
    finally:
        script.unlink(missing_ok=True)

    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node is not available")
class RingDashesTests(unittest.TestCase):
    def test_a_small_inbox_gets_one_segment_per_note(self):
        """The countable range: five notes, five dashes, and you can check it
        by looking."""
        rings = _rings([1, 2, 5, 9])["rings"]

        self.assertEqual([1, 2, 5, 9], [ring["segments"] for ring in rings])

    def test_a_large_inbox_clamps_to_the_cap(self):
        """128 notes is what this vault actually held. One dash each would be
        0.6px of ink — the ring would draw the same solid blur for 90, 128 and
        300, so it stops counting and says "full" instead."""
        result = _rings([12, 13, 128, 5000])

        self.assertEqual(12, result["cap"])
        self.assertEqual([12, 12, 12, 12],
                         [ring["segments"] for ring in result["rings"]])

    def test_an_empty_inbox_asks_for_no_dashes_at_all(self):
        """Zero is not "a ring with no segments" — the caller drops the dash
        array entirely and draws one muted circle. Returning a pattern here
        would make an empty Inbox look like a full one."""
        ring = _rings([0])["rings"][0]

        self.assertEqual(0, ring["segments"])
        self.assertEqual(0, ring["dash"])
        self.assertEqual(0, ring["gap"])

    def test_junk_counts_are_treated_as_empty(self):
        """`stats` arrives over the network; a missing root reaches this as
        undefined. NaN in a dash array silently blanks the whole stroke."""
        for count in (None, -4, "", "abc"):
            with self.subTest(count=count):
                self.assertEqual(0, _rings([count])["rings"][0]["segments"])

    def test_the_pattern_tiles_the_circle_exactly(self):
        """dash + gap must be the circumference divided by the segment count.
        Off by any amount and the dashes precess around the ring, leaving one
        fat segment where the pattern wraps."""
        for count in (1, 3, 7, 12, 40):
            with self.subTest(count=count):
                ring = _rings([count])["rings"][0]
                step = CIRCUMFERENCE / ring["segments"]

                self.assertAlmostEqual(step, ring["dash"] + ring["gap"], places=9)

    def test_every_painted_gap_is_the_same_whatever_the_count(self):
        """Round caps paint half a stroke width past each end of a dash, so the
        array asks for a gap one stroke wider than the one that shows. The shown
        gap is asserted, not the requested one, and it must not move between a
        ring of two and a ring of twelve."""
        for count in (2, 3, 6, 12, 128):
            with self.subTest(count=count):
                ring = _rings([count])["rings"][0]

                self.assertAlmostEqual(3, ring["gap"] - STROKE, places=9)

    def test_the_gap_is_small(self):
        """Two or three units: wide enough to read as separate dashes, narrow
        enough to read as one ring."""
        for count in (2, 12):
            gap = _rings([count])["rings"][0]["gap"] - STROKE

            self.assertTrue(2 <= gap <= 3)

    def test_one_note_is_a_solid_ring(self):
        """No gap and a dash as long as the circle: a single segment has no
        neighbour to be gapped from, and a bite out of the ring read as half a
        circle."""
        ring = _rings([1])["rings"][0]

        self.assertEqual(1, ring["segments"])
        self.assertAlmostEqual(CIRCUMFERENCE, ring["dash"], places=9)
        self.assertEqual(0, ring["gap"])

    def test_two_notes_are_two_dashes_with_gaps(self):
        ring = _rings([2])["rings"][0]

        self.assertGreater(ring["gap"], 0)
        self.assertAlmostEqual(CIRCUMFERENCE / 2, ring["dash"] + ring["gap"], places=9)

    def test_the_dash_is_never_negative(self):
        """A negative dash is not a thin segment, it is an invalid attribute:
        the browser throws the array out and draws a solid ring, so a full
        Inbox would look identical to an empty one."""
        for count in (1, 2, 12, 99):
            with self.subTest(count=count):
                self.assertGreater(_rings([count])["rings"][0]["dash"], 0)


@unittest.skipUnless(shutil.which("node"), "node is not available")
class CountLabelTests(unittest.TestCase):
    """What is drawn in the middle of the disc.

    The disc has about 51 units of clear width, so the label has to stay short
    enough to sit inside the grey border at a single fixed font size — the
    alternative, shrinking the type as digits accumulate, is a second size that
    only ever renders on counts nobody has.
    """

    def test_a_count_that_fits_is_shown_exactly(self):
        self.assertEqual(["0", "1", "42", "99"], _labels([0, 1, 42, 99]))

    def test_the_cap_is_ninety_nine(self):
        """Spelled out rather than read back from the module, which would pass
        for whatever the constant were changed to."""
        self.assertEqual(99, _rings([0])["countCap"])

    def test_anything_larger_collapses_to_the_cap(self):
        """100 is the first count that cannot be shown, and 128 is what this
        vault actually held before the Inbox cleanup."""
        self.assertEqual(["99+", "99+", "99+"], _labels([100, 128, 99999]))

    def test_the_label_never_exceeds_three_characters(self):
        """Three digits at 19px is ~33 units inside a ~51 unit disc. A fourth
        character is the one that starts crowding the border."""
        for count in (0, 9, 99, 100, 4321, 10 ** 9):
            with self.subTest(count=count):
                self.assertLessEqual(len(_labels([count])[0]), 3)

    def test_junk_counts_render_as_zero_rather_than_NaN(self):
        """`stats` arrives over the network; a missing root reaches this as
        undefined, and "NaN" in the disc is worse than a wrong number."""
        self.assertEqual(["0", "0", "0", "0"], _labels([None, -7, "", "abc"]))


if __name__ == "__main__":
    unittest.main()
