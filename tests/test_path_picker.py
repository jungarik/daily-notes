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

def _import_helper():
    """`api.contextmenu.helper` with the modules it pulls in put back.

    Two things have to be undone, not one. `api.*.db` imports the shared
    psycopg pool at module load and it is absent here, so `db` and
    `file_store` are stubbed for the duration of the import. But the import
    also *leaves* `api.contextmenu.db` and `.helper` in `sys.modules` and as
    attributes of their package — and `tests/test_contextmenu_delete.py`
    re-imports `helper` against a fake `db` to test the delete order. An
    `import a.b.c as x` resolves through the package attribute, so a module
    left behind here hands that file the real `db` and its four tests fail
    with no change to the code they cover.

    So: import, keep the module object, and remove every trace. The returned
    module keeps working — it is only unreachable by name.
    """
    stubbed = {}

    for name in ("db", "file_store"):
        if name not in sys.modules:
            stub = types.ModuleType(name)
            stub.cursor = lambda: None
            sys.modules[name] = stub
            stubbed[name] = stub

    try:
        from api.contextmenu import helper as imported
    finally:
        for name in stubbed:
            sys.modules.pop(name, None)

    import api.contextmenu as section

    for name in ("helper", "db"):
        sys.modules.pop("api.contextmenu." + name, None)

        if hasattr(section, name):
            delattr(section, name)

    return imported


helper = _import_helper()

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


SHEET = (ROOT / "browser" / "webapp" / "src" / "components"
         / "ContextMenu.jsx").read_text(encoding="utf-8")
SHEET_CSS = (ROOT / "browser" / "webapp" / "src"
             / "styles.css").read_text(encoding="utf-8")


class SheetOnOpenTests(unittest.TestCase):
    """What the sheet does the moment it opens.

    Component state rather than a pure helper, so this reads the source — the
    same trade `tests/test_addnote_keyboard.py` makes. The assertions are
    deliberately about the three decisions, not the syntax around them.
    """

    def test_the_path_is_selected_not_just_focused(self):
        """The path is usually being replaced, not edited: selecting it makes
        the first keystroke or Backspace clear the whole thing."""
        self.assertIn("input.select()", SHEET)

    def test_the_input_is_not_cleared_on_open(self):
        """Selecting keeps the path readable until the user types. Clearing it
        would throw away the only reference to where the note lives now."""
        self.assertIn('setVal(target.path || "")', SHEET)

    def test_the_selection_waits_for_the_slide_in(self):
        """Focusing mid-transition lands the caret in a moving element on iOS,
        which is why the focus is already deferred."""
        self.assertIn("}, 60);", SHEET)

    def test_the_list_is_hidden_until_the_input_is_touched(self):
        """On open the input holds the current path, so a list filtered by it
        shows that path and its children — the one place the note already is.
        `touched` is what keeps it out of the way until it has an answer."""
        self.assertIn("const [touched, setTouched] = useState(false);", SHEET)
        self.assertIn("const suggestions = touched", SHEET)

    def test_touched_resets_every_time_the_sheet_opens(self):
        """The sheet is reused for the next note. Without the reset the second
        open would start with yesterday's list showing."""
        self.assertIn("setTouched(false);", SHEET)

    def test_every_route_into_the_input_marks_it_touched(self):
        """Typing, clearing and picking a row all go through `edit`, so none of
        them can set the value while leaving the list hidden."""
        self.assertIn("const edit = (next) =>", SHEET)
        self.assertIn("onChange={(e) => edit(e.target.value)}", SHEET)
        self.assertNotIn("setVal(e.target.value)", SHEET)

    def test_the_clear_button_exists_and_is_scoped_to_the_sheet(self):
        self.assertIn('className="path-clear"', SHEET)
        self.assertIn("#pathSheet .path-clear {", SHEET_CSS)

    def test_the_clear_button_is_labelled(self):
        """Its glyph is a bare ✕, which a screen reader reads as nothing."""
        self.assertIn('aria-label="Clear path"', SHEET)

    def test_the_clear_button_goes_through_edit_too(self):
        """Clearing opens the list, and an empty query is every path — which
        is the point of reaching for it."""
        self.assertIn('edit("");', SHEET)

    def test_the_input_leaves_room_for_the_clear_button(self):
        """Absolutely positioned over the field: without the right padding the
        path's tail runs under the glyph."""
        start = SHEET_CSS.index("#pathSheet .path-input {")
        rule = SHEET_CSS[start:SHEET_CSS.index("}", start)]

        self.assertIn("padding: 11px 40px 11px 12px", rule)


if __name__ == "__main__":
    unittest.main()
