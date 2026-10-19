"""The View note page and its section.

A deliberate copy of the Add note page opened on an existing note, with reads
only. These tests pin the decisions that make it a separate thing rather than a
second route to the editor: its own section, its own styles, no write path, and
the Explorer long press that opens it without also firing the tap.

Like the other page tests it reads source (the Mini App cannot run under
unittest); the endpoint was also executed against a stubbed `db` inside the API
image when it was written.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SECTION = ROOT / "api" / "viewnote"
SRC = ROOT / "browser" / "webapp" / "src"


def _read(path):
    return path.read_text(encoding="utf-8")


ENDPOINTS = _read(SECTION / "endpoints.py")
DB_SOURCE = _read(SECTION / "db.py")
MAIN = _read(ROOT / "api" / "main.py")
PAGE = _read(SRC / "components" / "ViewNote.jsx")
EXPLORER = _read(SRC / "components" / "Explorer.jsx")
CSS = _read(SRC / "styles.css")
API_JS = _read(SRC / "lib" / "api.js")
CONTEXT = _read(SRC / "store" / "AppContext.jsx")
APP = _read(SRC / "App.jsx")


class SectionTests(unittest.TestCase):
    def test_it_is_a_section_with_the_three_files(self):
        for name in ("endpoints.py", "helper.py", "db.py", "schemas.py"):
            with self.subTest(file=name):
                self.assertTrue((SECTION / name).exists())

    def test_it_is_registered_under_its_own_prefix(self):
        self.assertIn('prefix="/api/viewnote"', ENDPOINTS)
        self.assertIn("app.include_router(viewnote_router)", MAIN)

    def test_it_imports_no_other_section(self):
        for name in ("endpoints.py", "helper.py", "db.py", "schemas.py"):
            with self.subTest(file=name):
                self.assertNotRegex(_read(SECTION / name), r"api\.(addnote|contextmenu|notesheet|feed)")

    def test_reads_only(self):
        for verb in ("post", "put", "delete", "patch"):
            self.assertNotIn(f"@router.{verb}(", ENDPOINTS)

        self.assertNotRegex(DB_SOURCE, r"\b(INSERT|UPDATE|DELETE)\b")

    def test_roots_and_children_are_declared_before_the_note(self):
        order = [ENDPOINTS.index(f'@router.get("{route}"') for route in ("/roots", "/children", "/{note_id}")]

        self.assertEqual(sorted(order), order)

    def test_the_owner_predicate_is_in_the_query(self):
        self.assertIn("WHERE id = %s AND user_id = %s", DB_SOURCE)
        self.assertIn("status_code=404", ENDPOINTS)

    def test_nullable_columns_are_coerced(self):
        for column in ("text", "path"):
            self.assertIn(f'row["{column}"] or ""', ENDPOINTS)

        self.assertIn('row["tags"] or []', ENDPOINTS)

    def test_no_storage_key_leaves_the_api(self):
        self.assertNotIn("storage_key", DB_SOURCE)


class PageTests(unittest.TestCase):
    def test_it_is_mounted_and_driven_by_its_own_state(self):
        self.assertIn("<ViewNote note_id={state.viewNoteId} />", APP)
        self.assertIn("viewNoteOpen", CONTEXT)
        self.assertIn("const openViewNote", CONTEXT)
        self.assertIn("const closeViewNote", CONTEXT)

    def test_it_reads_through_its_own_client_calls(self):
        for call in ("fetchViewNote", "listViewNoteRoots", "listViewNoteChildren"):
            with self.subTest(call=call):
                self.assertIn(call, PAGE)

        self.assertIn('"/api/viewnote/"', API_JS)
        self.assertNotRegex(PAGE, r"addnote|createNote|saveNote")

    def test_the_note_read_has_no_catch(self):
        block = API_JS.split("export const fetchViewNote")[1].split("export const")[0]

        self.assertNotIn(".catch", block)

    def test_it_cannot_write(self):
        self.assertIn("readOnly", PAGE)
        self.assertNotIn('aria-label="Save"', PAGE)
        self.assertNotIn("fab commit", PAGE)
        self.assertNotRegex(PAGE, r"\b(apiPost|apiPut|createNote|saveNote)\b")

    def test_it_carries_no_keyboard_machinery(self):
        for name in ("visualViewport", "visibleViewport", "addNoteInputRef"):
            self.assertNotIn(name, PAGE)

    def test_it_shares_only_the_wheel_and_the_glyphs(self):
        imports = re.findall(r'from "(\./[^"]+)"', PAGE)

        self.assertEqual(["./PathWheel.jsx", "./glyphs.jsx"], sorted(imports))

    def test_a_failed_read_stays_open_with_a_message(self):
        self.assertIn("Couldn’t load this note.", PAGE)

    def test_it_has_its_own_styles_scoped_to_show(self):
        for selector in (".viewnote {", ".viewnote.show {", ".viewnote.show .viewnote-close",
                         ".viewnote.show .viewnote-side", ".viewnote-body {"):
            with self.subTest(selector=selector):
                self.assertIn(selector, CSS)

        self.assertNotIn("viewnote", _read(SRC / "components" / "AddNote.jsx"))


class EditButtonTests(unittest.TestCase):
    def test_back_is_bottom_left_a_chevron_and_as_big_as_edit(self):
        self.assertNotIn("viewnote-bar", PAGE + CSS)
        self.assertIn('className="fab viewnote-close"', PAGE)
        self.assertIn('aria-label="Back"', PAGE)
        self.assertIn('<path d="M14.5 5.5 8 12l6.5 6.5" />', PAGE)
        self.assertNotIn("M6 6l12 12", PAGE)

        rule = CSS.split("  .viewnote-close {", 1)[1].split("}", 1)[0]

        self.assertIn("left: 12px;", rule)
        self.assertIn("width: 62px; height: 62px;", rule)
        self.assertIn(".viewnote-close svg { width: 23px; height: 23px; }", CSS)
        self.assertIn("width: 62px; height: 62px;", CSS.split("  .viewnote-edit {", 1)[1].split("}", 1)[0])

    def test_close_and_edit_share_a_baseline(self):
        bottom = "bottom: calc(30px + env(safe-area-inset-bottom, 0px));"

        for selector in ("  .viewnote-close {", "  .viewnote-edit {"):
            self.assertIn(bottom, CSS.split(selector, 1)[1].split("}", 1)[0])

    def test_the_chat_button_is_a_bubble_not_the_sparkle(self):
        button = PAGE.split('className="fab viewnote-ai"', 1)[1].split("</button>", 1)[0]

        self.assertIn('aria-label="Chat"', button)
        self.assertIn("disabled", button)
        self.assertNotIn("M12 3.2l1.9", button)

    def test_edit_opens_the_editor_by_id_and_passes_nothing_else(self):
        self.assertIn("openAddNote(note_id)", PAGE)

    def test_edit_is_fifteen_percent_over_the_bar_circle_on_the_side_inset(self):
        rule = CSS.split("  .viewnote-edit {", 1)[1].split("}", 1)[0]

        self.assertIn("right: 12px;", rule)
        self.assertIn("width: 62px; height: 62px;", rule)
        self.assertIn(".viewnote.show .viewnote-edit", CSS)

    def test_the_editor_stacks_above_the_viewer(self):
        z = lambda sel: int(re.search(re.escape(sel) + r" \{\s*position: fixed; inset: 0; z-index: (\d+)", CSS).group(1))

        self.assertGreater(z(".addnote"), z(".viewnote"))

    def test_the_page_rereads_after_the_editor_closes(self):
        self.assertIn("editing", PAGE)
        self.assertIn("[open, note_id, editing]", PAGE)


class LongPressTests(unittest.TestCase):
    def test_it_uses_the_maps_numbers(self):
        self.assertIn("const LONG_PRESS_MS = 450;", EXPLORER)
        self.assertIn("const TAP_SLOP = 6;", EXPLORER)

    def test_a_long_press_opens_the_page(self):
        self.assertIn("openViewNote(note.id)", EXPLORER)

    def test_the_following_click_is_swallowed(self):
        self.assertIn("press.current.fired", EXPLORER)

    def test_movement_past_the_slop_cancels(self):
        self.assertIn("> TAP_SLOP", EXPLORER)

    def test_the_native_menu_is_suppressed_and_the_row_highlights(self):
        self.assertIn("onContextMenu={(e) => e.preventDefault()}", EXPLORER)
        self.assertIn(".row.file.pressing", CSS)
        self.assertIn("-webkit-touch-callout: none", CSS)

    def test_only_note_rows_have_it(self):
        folder = EXPLORER.split("function Folder(")[1].split("export default")[0]

        self.assertNotIn("openViewNote", folder)

    def test_the_menu_dots_do_not_start_a_press(self):
        self.assertIn('closest(".dots")', EXPLORER)


if __name__ == "__main__":
    unittest.main()
