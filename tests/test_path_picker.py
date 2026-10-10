"""The change-path sheet: two stacked selectors, root over sub-folder.

Three halves, pinned the way the repo pins each. `root_labels` is a pure Python
mapper and runs directly. `splitPath` / `joinPath` / `swapRoot` / `filterNames`
are the Mini App's own logic and run under node, against the real module, so
the test breaks if the source does. The sheet itself is component state, so its
decisions are read from the source — the same trade `tests/test_addnote_keyboard.py`
makes — and the two endpoints are executed against a recording fake `db`.

What is worth the assertions is not the happy path. It is that every root is
offered even when empty (otherwise the picker can't file a note anywhere new),
that the sub-folder read is owner-scoped and filtered in SQL, that a folder only
moves between roots with the rest of its path carried along, and that changing
the root cannot leave a stale sub-folder behind.
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


class RootLabelTests(unittest.TestCase):
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

    def test_every_root_is_offered(self):
        """Empty ones included: a root with nothing in it is precisely where a
        user wants to move a note. The roster has no per-note input at all."""
        self.assertEqual(len(helper.root_labels("en")), len(set(helper.root_labels("en"))))

    def test_root_labels_are_one_language_at_a_time(self):
        """`clean_root_path` accepts a root typed in any supported language,
        but offering every translation in the picker is noise."""
        self.assertNotEqual(helper.root_labels("en"), helper.root_labels("uk"))

    def test_it_is_a_pure_mapper(self):
        self.assertEqual(helper.root_labels("en"), helper.root_labels("en"))

    def test_the_old_all_paths_roster_is_gone(self):
        self.assertFalse(hasattr(helper, "known_paths"))


SCRIPT = """
import { splitPath, joinPath, swapRoot, filterNames } from %s;
const [fn, args] = JSON.parse(process.argv[2]);
console.log(JSON.stringify({ splitPath, joinPath, swapRoot, filterNames }[fn](...args)));
"""


def _js(fn, *args):
    """A client helper, through the real module."""
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "path_picker.mjs"
        script.write_text(SCRIPT % json.dumps(FORMAT_JS.as_posix()), encoding="utf-8")
        out = subprocess.run(
            ["node", str(script), json.dumps([fn, list(args)])],
            capture_output=True, text=True, check=True)

    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node is not available")
class PathPartsTests(unittest.TestCase):
    def test_a_path_splits_into_root_and_sub_folder(self):
        self.assertEqual({"root": "Projects", "child": "api"}, _js("splitPath", "Projects/api"))

    def test_a_root_alone_has_no_sub_folder(self):
        self.assertEqual({"root": "Projects", "child": ""}, _js("splitPath", "Projects"))

    def test_nothing_splits_to_nothing(self):
        self.assertEqual({"root": "", "child": ""}, _js("splitPath", None))
        self.assertEqual({"root": "", "child": ""}, _js("splitPath", ""))

    def test_a_deeper_path_is_truncated_to_two_levels(self):
        """The vault has two levels; the sheet edits those and saving drops the
        rest."""
        self.assertEqual({"root": "Projects", "child": "api"}, _js("splitPath", "Projects/api/v2"))

    def test_an_empty_sub_folder_is_the_root_itself(self):
        self.assertEqual("Projects", _js("joinPath", "Projects", ""))

    def test_a_sub_folder_joins_its_root(self):
        self.assertEqual("Projects/api", _js("joinPath", "Projects", "api"))

    def test_a_folder_moves_between_roots_keeping_its_name(self):
        self.assertEqual("Areas/api", _js("swapRoot", "Projects/api", "Areas"))

    def test_a_folder_move_carries_the_rest_of_the_path(self):
        self.assertEqual("Areas/api/v2", _js("swapRoot", "Projects/api/v2", "Areas"))

    def test_typing_narrows_the_names_ignoring_case(self):
        self.assertEqual(["Alpha"], _js("filterNames", ["Alpha", "Beta"], "alp"))

    def test_an_empty_query_shows_everything(self):
        self.assertEqual(["Alpha", "Beta"], _js("filterNames", ["Alpha", "Beta"], "   "))

    def test_a_query_matching_nothing_offers_nothing(self):
        """Which is the new-name case: no rows, and the typed text is the
        answer. There is no mode to switch into."""
        self.assertEqual([], _js("filterNames", ["Alpha"], "zzz"))


ENDPOINTS = (ROOT / "api" / "contextmenu" / "endpoints.py").read_text(encoding="utf-8")
DB_SOURCE = (ROOT / "api" / "contextmenu" / "db.py").read_text(encoding="utf-8")


class RosterEndpointTests(unittest.TestCase):
    def test_the_old_all_paths_route_is_gone(self):
        self.assertNotIn('@router.get("/paths"', ENDPOINTS)
        self.assertNotIn("def list_paths", DB_SOURCE)

    def test_both_rosters_exist(self):
        self.assertIn('@router.get("/roots"', ENDPOINTS)
        self.assertIn('@router.get("/children"', ENDPOINTS)

    def test_the_children_are_owner_scoped(self):
        self.assertIn("WHERE user_id = %s AND split_part(path, '/', 1) = %s", DB_SOURCE)

    def test_the_children_are_filtered_in_sql_not_in_python(self):
        """Choosing a root should read that root's notes, not the vault. And
        the root is matched as a whole segment: `LIKE 'Projects%'` would also
        catch `Projects2/x`."""
        statement = DB_SOURCE.split("def list_subfolders", 1)[1].split('"""', 3)[3]

        self.assertIn("split_part(path, '/', 2)", statement)
        self.assertNotIn("LIKE", statement)

    def test_the_roots_read_no_notes(self):
        """The fixed roots need the locale and nothing else."""
        roots = ENDPOINTS.split('@router.get("/roots"', 1)[1].split("@router", 1)[0]

        self.assertNotIn("list_subfolders", roots)
        self.assertIn("helper.root_labels(locale)", roots)

    def test_the_section_owns_its_reads(self):
        self.assertNotIn("api.addnote", ENDPOINTS)


SHEET = (ROOT / "browser" / "webapp" / "src" / "components"
         / "ContextMenu.jsx").read_text(encoding="utf-8")
SHEET_CSS = (ROOT / "browser" / "webapp" / "src"
             / "styles.css").read_text(encoding="utf-8")
PICKER = SHEET[SHEET.index("function PathSheet"):]


class SheetTests(unittest.TestCase):
    """What the sheet decides. Component state rather than a pure helper, so
    this reads the source; the assertions are about the decisions, not the
    syntax around them."""

    def test_there_are_two_fields_for_a_note_and_one_for_a_folder(self):
        self.assertIn('aria-label="Folder"', PICKER)
        self.assertIn('aria-label="Sub-folder"', PICKER)
        self.assertIn("{!isFolder && (", PICKER)

    def test_a_folder_only_moves_between_roots(self):
        """No third level exists, so the folder's sheet is the root field alone
        and the rest of its path travels with it."""
        self.assertIn("swapRoot(target.path, chosenRoot)", PICKER)
        self.assertIn('"Move folder"', PICKER)

    def test_a_folder_cannot_be_moved_to_where_it_already_is(self):
        self.assertIn("next === target.path", PICKER)

    def test_choosing_a_different_root_clears_the_sub_folder(self):
        """A stale "Projects/api" must not survive a move to Areas — and
        re-picking the same root must not wipe the sub-folder."""
        self.assertIn('if (next !== root) setChild("");', PICKER)

    def test_the_sub_folders_are_read_for_the_chosen_root(self):
        self.assertIn("listChildren(root)", PICKER)
        self.assertIn("}, [target, isFolder, root]);", PICKER)

    def test_the_sub_folder_waits_for_a_root(self):
        self.assertIn("disabled={!root.trim()}", PICKER)

    def test_the_root_field_is_read_only_while_there_is_a_roster(self):
        """The server rejects an unknown root, so typing one only ends in a
        422 — but if the read failed the field falls back to typing."""
        self.assertIn("readOnly={roots.length > 0}", PICKER)

    def test_an_empty_sub_folder_saves_the_root_itself(self):
        self.assertIn("joinPath(chosenRoot, child.trim())", PICKER)

    def test_a_typed_slash_is_dropped(self):
        self.assertIn(r'.replace(/[\\/]/g, "")', PICKER)

    def test_a_row_tap_does_not_blur_the_field(self):
        """Otherwise the field's blur closes the list before the tap lands."""
        self.assertIn("onMouseDown={keepFocus}", PICKER)

    def test_the_state_resets_every_time_the_sheet_opens(self):
        """The sheet is reused for the next note."""
        self.assertIn("setChild(target.type === \"folder\" ? \"\" : current.child);", PICKER)
        self.assertIn('setOpenField("");', PICKER)

    def test_the_clear_button_is_labelled_and_scoped_to_the_sheet(self):
        self.assertIn('aria-label="Clear sub-folder"', PICKER)
        self.assertIn("#pathSheet .path-clear {", SHEET_CSS)

    def test_the_input_leaves_room_for_the_clear_button(self):
        start = SHEET_CSS.index("#pathSheet .path-input {")
        rule = SHEET_CSS[start:SHEET_CSS.index("}", start)]

        self.assertIn("padding: 11px 40px 11px 12px", rule)

    def test_the_old_roster_helpers_are_gone(self):
        fmt = FORMAT_JS.read_text(encoding="utf-8")

        self.assertNotIn("selectablePaths", fmt)
        self.assertNotIn("filterPaths", fmt)
        self.assertNotIn("listPaths", SHEET)


if __name__ == "__main__":
    unittest.main()
