"""The change-path picker: the roster the server offers, and the filtering the
client does to it.

Two halves, pinned the way the repo pins each: `known_paths` is a pure Python
mapper and runs directly; `selectablePaths` / `filterPaths` are the Mini App's
own logic and run under node, against the real module, so the test breaks if
the source does.

What is worth the assertions is not the happy path. It is that an empty root
folder is still offered (otherwise the picker can't file a note anywhere new),
that an unknown root sorts late instead of vanishing (otherwise a language
switch hides notes), and that a folder is never offered its own subtree as a
destination.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
FORMAT_JS = ROOT / "browser" / "webapp" / "src" / "lib" / "format.js"

# `api.*.db` imports the shared psycopg pool at module load, which is absent
# here. Stub it just long enough to import, then take it back out — leaving a
# fake `db` in `sys.modules` changes how other test modules import.
_had_db = "db" in sys.modules

if not _had_db:
    _stub = types.ModuleType("db")
    _stub.cursor = lambda: None
    sys.modules["db"] = _stub

_had_store = "file_store" in sys.modules

if not _had_store:
    sys.modules["file_store"] = types.ModuleType("file_store")

from api.contextmenu import helper            # noqa: E402

if not _had_db:
    del sys.modules["db"]

if not _had_store:
    del sys.modules["file_store"]

ROOTS = ["Inbox", "Projects", "Areas", "Resources", "Archive"]


class KnownPathsTests(unittest.TestCase):
    def test_every_root_is_offered_even_when_empty(self):
        """The point of the picker. A root with nothing in it is precisely
        where a user wants to move a note, and if it is absent the only way
        there is to type it exactly right."""
        offered = helper.known_paths(ROOTS, ["Projects/api"])

        for root in ROOTS:
            with self.subTest(root=root):
                self.assertIn(root, offered)

    def test_paths_group_under_their_root_in_canonical_order(self):
        """Not alphabetical: Areas before Inbox would be alphabetical, and the
        vault's order is Inbox, Projects, Areas, Resources, Archive."""
        offered = helper.known_paths(ROOTS, ["Areas/health", "Projects/api"])

        self.assertEqual(
            ["Inbox", "Projects", "Projects/api", "Areas", "Areas/health",
             "Resources", "Archive"],
            offered,
        )

    def test_a_root_sorts_above_its_own_children(self):
        """`Projects` is a destination too, and burying it among its
        sub-folders makes "just put it in Projects" a hunt."""
        offered = helper.known_paths(ROOTS, ["Projects/zebra", "Projects/alpha"])
        projects = [path for path in offered if path.startswith("Projects")]

        self.assertEqual(["Projects", "Projects/alpha", "Projects/zebra"], projects)

    def test_an_unrecognised_root_sorts_after_the_known_ones(self):
        """A path left behind by a language switch. Dropping it would hide the
        only route back to those notes, so it lands at the end instead."""
        offered = helper.known_paths(ROOTS, ["Проєкти/old"])

        self.assertEqual("Проєкти/old", offered[-1])
        self.assertIn("Проєкти/old", offered)

    def test_duplicates_collapse(self):
        """A root that is also a note's path arrives from both sources."""
        offered = helper.known_paths(ROOTS, ["Inbox", "Inbox", "Projects"])

        self.assertEqual(len(set(offered)), len(offered))

    def test_blank_paths_are_dropped(self):
        """A whitespace row would render as an unlabelled tappable line."""
        self.assertNotIn("", helper.known_paths(ROOTS, ["", "   "]))

    def test_it_is_a_pure_mapper(self):
        """The endpoint is the impure boundary (api/README). Called twice with
        equal arguments this returns equal output and leaves its inputs alone."""
        roots, paths = list(ROOTS), ["Projects/api"]
        first = helper.known_paths(roots, paths)

        self.assertEqual(first, helper.known_paths(roots, paths))
        self.assertEqual(ROOTS, roots)
        self.assertEqual(["Projects/api"], paths)

    def test_root_labels_follow_the_shared_root_order(self):
        """`common.helper.order_root_keys()` is the one source of that order;
        this asserts the labels come out in it rather than restating it."""
        import config
        import i18n
        from common import helper as common_helper

        self.assertEqual(
            [i18n.t("en", key) for key in common_helper.order_root_keys()],
            helper.root_labels("en"),
        )
        self.assertEqual(len(config.ROOT_FOLDERS), len(helper.root_labels("en")))

    def test_root_labels_are_one_language_at_a_time(self):
        """`clean_root_path` accepts a root typed in any supported language,
        but offering every translation in the dropdown is noise."""
        self.assertNotEqual(helper.root_labels("en"), helper.root_labels("uk"))


SCRIPT = """
import { selectablePaths, filterPaths } from %s;
const [paths, target, query] = JSON.parse(process.argv[2]);
console.log(JSON.stringify(filterPaths(selectablePaths(paths, target), query)));
"""


def _offered(paths, target, query=""):
    """What the sheet would list, through the real client helpers."""
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "path_picker.mjs"
        script.write_text(SCRIPT % json.dumps(FORMAT_JS.as_posix()), encoding="utf-8")
        out = subprocess.run(
            ["node", str(script), json.dumps([paths, target, query])],
            capture_output=True, text=True, check=True)

    return json.loads(out.stdout)


PATHS = ["Inbox", "Projects", "Projects/api", "Projects/api/v2", "Areas/health"]
NOTE = {"type": "note", "id": 1, "path": "Inbox"}
FOLDER = {"type": "folder", "path": "Projects/api"}


@unittest.skipUnless(shutil.which("node"), "node is not available")
class PathFilterTests(unittest.TestCase):
    def test_a_note_may_be_offered_anything(self):
        self.assertEqual(PATHS, _offered(PATHS, NOTE))

    def test_a_folder_is_not_offered_itself(self):
        """Renaming `Projects/api` to `Projects/api` is a tap that does
        nothing, and the sheet would still report success."""
        self.assertNotIn("Projects/api", _offered(PATHS, FOLDER))

    def test_a_folder_is_not_offered_its_own_descendants(self):
        """A folder cannot become a child of itself."""
        self.assertNotIn("Projects/api/v2", _offered(PATHS, FOLDER))

    def test_a_folder_keeps_every_unrelated_destination(self):
        """The exclusion is the subtree, not the root: `Projects` is still
        where you would move `Projects/api` to flatten it."""
        offered = _offered(PATHS, FOLDER)

        self.assertEqual(["Inbox", "Projects", "Areas/health"], offered)

    def test_a_prefix_match_is_not_a_subtree_match(self):
        """`Projects/apiv2` starts with `Projects/api` as a string but is a
        sibling, not a child — which is why the filter tests for the slash."""
        offered = _offered(PATHS + ["Projects/apiv2"], FOLDER)

        self.assertIn("Projects/apiv2", offered)

    def test_typing_narrows_the_list(self):
        self.assertEqual(["Projects/api", "Projects/api/v2"],
                         _offered(PATHS, NOTE, "api"))

    def test_the_filter_ignores_case(self):
        """The roots are capitalised and nobody types them that way."""
        self.assertEqual(["Inbox"], _offered(PATHS, NOTE, "inb"))

    def test_an_empty_query_shows_everything(self):
        """On open the input holds the note's current path; the list's job is
        still to show what exists, not to narrow to one row."""
        self.assertEqual(PATHS, _offered(PATHS, NOTE, "   "))

    def test_a_query_matching_nothing_offers_nothing(self):
        """Which is the new-path case: no rows, and the typed text is the
        answer. There is no mode to switch into."""
        self.assertEqual([], _offered(PATHS, NOTE, "Projects/brand-new"))


if __name__ == "__main__":
    unittest.main()
