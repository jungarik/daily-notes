"""`compareRoots` from the Mini App, executed rather than read.

The comparator is the only real logic the front end contributes to root
ordering, and its interesting case — a folder that is not on the roster — is
exactly the one a reader skims past. Node runs the actual module, so this
breaks if the source does.

Skipped when node is unavailable; the Python suite must stay runnable without
a JS toolchain.
"""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
FORMAT_JS = ROOT / "browser" / "webapp" / "src" / "lib" / "format.js"

SCRIPT = """
import { compareRoots } from %s;
const [roots, names] = JSON.parse(process.argv[2]);
console.log(JSON.stringify(names.sort(compareRoots(roots))));
"""


def _sorted(roots, names):
    """Sort `names` with the real comparator, under node."""
    script = ROOT / "tests" / ".compare_roots.mjs"
    script.write_text(SCRIPT % json.dumps(FORMAT_JS.as_posix()), encoding="utf-8")
    try:
        out = subprocess.run(
            ["node", str(script), json.dumps([roots, names])],
            capture_output=True, text=True, check=True)
    finally:
        script.unlink(missing_ok=True)

    return json.loads(out.stdout)


ROSTER = [
    {"key": "folder_inbox", "label": "Вхідні"},
    {"key": "folder_projects", "label": "Проєкти"},
    {"key": "folder_areas", "label": "Сфери"},
    {"key": "folder_resources", "label": "Матеріали"},
    {"key": "folder_archive", "label": "Архів"},
]


@unittest.skipUnless(shutil.which("node"), "node is not available")
class CompareRootsTests(unittest.TestCase):
    def test_roster_order_beats_the_alphabet(self):
        """Alphabetically Архів leads in Ukrainian, which is what the Explorer
        used to show. The roster is what stops that."""
        names = ["Архів", "Матеріали", "Проєкти", "Сфери", "Вхідні"]

        self.assertEqual(["Вхідні", "Проєкти", "Сфери", "Матеріали", "Архів"],
                         _sorted(ROSTER, names))

    def test_an_unknown_root_sorts_after_the_known_ones(self):
        """A root left behind by a language switch, or typed by hand. Dropping
        it would hide notes; leading with it would be noise."""
        names = ["Projects", "Архів", "Вхідні"]

        self.assertEqual(["Вхідні", "Архів", "Projects"], _sorted(ROSTER, names))

    def test_unknown_roots_are_alphabetical_among_themselves(self):
        names = ["Zebra", "Apple", "Вхідні"]

        self.assertEqual(["Вхідні", "Apple", "Zebra"], _sorted(ROSTER, names))

    def test_an_empty_roster_degrades_to_alphabetical(self):
        """What the client sees if the roster never arrives — the old
        behaviour, not a crash or an arbitrary order.

        The expected order is written out rather than computed with Python's
        `sorted`: that is code-point order, while the comparator uses JS
        `localeCompare`. They agree on these three strings, which would make a
        derived expectation pass for the wrong reason.
        """
        names = ["Проєкти", "Архів", "Вхідні"]

        self.assertEqual(["Архів", "Вхідні", "Проєкти"], _sorted([], names))


if __name__ == "__main__":
    unittest.main()
