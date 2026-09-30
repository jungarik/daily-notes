"""Deleting a note from the web app's ⋮ menu.

Two properties carry the weight, and neither shows up in a manual test that
happens to pass:

* **Order.** The bucket keys must be read before the row goes. `note_attachments`
  cascades, so reading them afterwards returns nothing — the delete still looks
  successful and every photo stays in the bucket with nothing left to identify
  it. This is the same mistake the one-off SQL cleanup had to be careful about.
* **Tenancy.** The delete is scoped by `user_id`. Without that predicate any
  authenticated caller could destroy any note by guessing an id, and the guard
  is invisible until someone tries.

`db` and `file_store` are stubbed and restored around each test; a fake `db`
left in `sys.modules` lets unrelated modules import further than they should.
"""

import ast
import re
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
DB_SOURCE = (ROOT / "api" / "contextmenu" / "db.py").read_text(encoding="utf-8")
MENU_SOURCE = (ROOT / "browser" / "webapp" / "src" / "components"
               / "ContextMenu.jsx").read_text(encoding="utf-8")

# The same file with comments removed. Checks for what the component *does*
# have to run against this: the comments explain why a native dialog is avoided
# and therefore contain the very string such a check looks for. Crude — it
# would also cut `//` inside a string literal — but this file has none, and the
# alternative is parsing JSX to ask one question.
MENU_CODE = re.sub(r"//[^\n]*|/\*(?:.|\n)*?\*/", "", MENU_SOURCE)


class HelperTests(unittest.TestCase):
    """`helper.delete_note` against a stubbed section db and bucket."""

    def setUp(self):
        self.journal = []
        self.purged = []
        self.failing = ()
        self.owns = True

        real = {name: sys.modules.get(name)
                for name in ("api.contextmenu.db", "file_store")}

        def restore():
            for name, module in real.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

        self.addCleanup(restore)
        self.addCleanup(sys.modules.pop, "api.contextmenu.helper", None)

        fake_db = types.ModuleType("api.contextmenu.db")
        fake_db.object_keys = self._object_keys
        fake_db.delete_note = self._delete_note
        sys.modules["api.contextmenu.db"] = fake_db

        fake_store = types.ModuleType("file_store")
        fake_store.delete_object = self._delete_object
        sys.modules["file_store"] = fake_store

        sys.modules.pop("api.contextmenu.helper", None)
        import api.contextmenu.helper as helper

        self.helper = helper

    def _object_keys(self, note_id):
        self.journal.append("keys")

        return ["attachments/image/a.jpg", "audio/v.oga"]

    def _delete_note(self, user_id, note_id):
        self.journal.append("delete")

        return self.owns

    def _delete_object(self, key):
        self.journal.append("purge")
        self.purged.append(key)

        return key not in self.failing

    def test_the_keys_are_read_before_the_row_goes(self):
        self.helper.delete_note(1, 11)

        self.assertEqual(["keys", "delete", "purge", "purge"], self.journal)

    def test_a_successful_delete_purges_every_object(self):
        self.assertEqual("ok", self.helper.delete_note(1, 11))
        self.assertEqual(["attachments/image/a.jpg", "audio/v.oga"], self.purged)

    def test_someone_elses_note_is_not_found_and_purges_nothing(self):
        """The row delete is what enforces ownership, so a miss must stop the
        purge — otherwise a caller could wipe another user's attachments while
        being told the note does not exist."""
        self.owns = False

        self.assertEqual("not_found", self.helper.delete_note(2, 11))
        self.assertEqual([], self.purged)

    def test_a_failed_purge_still_reports_success(self):
        """The row is already gone. Reporting failure would tell the user the
        note survived when it did not; the orphan is logged instead."""
        self.failing = ("audio/v.oga",)

        self.assertEqual("ok", self.helper.delete_note(1, 11))


class TenancySqlTests(unittest.TestCase):
    """The guard lives in SQL, so it is read rather than executed."""

    def _body(self, name):
        """The function's statements, without its docstring.

        The docstring has to go: `delete_note`'s explains what cascades and so
        names `note_links` and `reminders`, which made the "no conditions"
        assertion below fail on its own documentation.

        `ast` rather than a regex, because a regex for triple-quoted strings
        cannot tell a docstring from `object_keys`'s triple-quoted SQL — the
        first attempt deleted the query it was meant to inspect.
        """
        tree = ast.parse(DB_SOURCE)
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == name)
        statements = function.body[1:] if ast.get_docstring(function) else function.body

        return "\n".join(ast.get_source_segment(DB_SOURCE, stmt) for stmt in statements)

    def test_the_delete_is_scoped_to_the_owner(self):
        body = self._body("delete_note")

        self.assertRegex(body, r"DELETE FROM notes\s+WHERE id = %s AND user_id = %s")

    def test_the_delete_reports_whether_a_row_went(self):
        """Without RETURNING there is no way to tell "deleted" from "not
        yours", and the endpoint would answer 204 to both."""
        self.assertIn("RETURNING id", self._body("delete_note"))

    def test_the_key_query_covers_attachments_and_voice_audio(self):
        body = self._body("object_keys")

        self.assertIn("FROM note_attachments", body)
        self.assertIn("audio_key", body)

    def test_it_is_not_the_bots_conditional_delete(self):
        """`api/telegram_bot.delete_if_bare` refuses a note that is filed,
        linked or has a live reminder. This one is the web app's Delete: the
        user asked, so those conditions must not be here."""
        body = self._body("delete_note")

        self.assertNotIn("path IS NULL", body)
        self.assertNotIn("note_links", body)
        self.assertNotIn("reminders", body)


class MenuTests(unittest.TestCase):
    def test_delete_is_offered_for_notes_only(self):
        """A folder is a path prefix, not an object — a folder Delete would
        silently mean "destroy everything filed under this"."""
        self.assertIn('ctx.target.type === "note"', MENU_SOURCE)

    def test_the_menu_entry_and_the_button_are_both_destructive(self):
        self.assertIn('className="ctx-item danger"', MENU_SOURCE)
        self.assertIn('className="path-btn danger"', MENU_SOURCE)

    def test_it_does_not_use_a_native_confirm(self):
        """A native `confirm()` is browser chrome inside Telegram's webview:
        unstylable, and suppressed outright by some in-app webviews — which
        would make Delete appear to do nothing.

        Run against MENU_CODE, and matching `window.confirm` rather than a bare
        `confirm(`: the component's handler used to be called `confirm` and its
        comments discuss the native one, so looser checks kept flagging the very
        code and prose that exist to avoid the dialog."""
        self.assertNotIn("window.confirm", MENU_CODE)
        self.assertNotIn("alert(", MENU_CODE)

    def test_the_confirmation_says_what_else_goes(self):
        for word in ("undone", "reminders", "links"):
            with self.subTest(word=word):
                self.assertIn(word, MENU_SOURCE)


class ContrastTests(unittest.TestCase):
    """The two reds are different on purpose; one cannot do both jobs."""

    CSS = (ROOT / "browser" / "webapp" / "src" / "styles.css").read_text(encoding="utf-8")

    @staticmethod
    def _ratio(fg, bg):
        def channel(value):
            value /= 255

            return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

        def luminance(colour):
            colour = colour.lstrip("#")
            red, green, blue = (int(colour[i:i + 2], 16) for i in (0, 2, 4))

            return (0.2126 * channel(red) + 0.7152 * channel(green)
                    + 0.0722 * channel(blue))

        high, low = sorted((luminance(fg), luminance(bg)), reverse=True)

        return (high + 0.05) / (low + 0.05)

    def _var(self, name):
        return re.search(rf"--{name}:\s*(#[0-9a-fA-F]{{6}})", self.CSS).group(1)

    def test_white_is_legible_on_the_fill_red(self):
        self.assertGreaterEqual(self._ratio("#ffffff", self._var("danger")), 4.5)

    def test_the_label_red_is_legible_on_the_menu(self):
        """The menu's surface is --bg-elev, not --bg."""
        self.assertGreaterEqual(
            self._ratio(self._var("danger-text"), self._var("bg-elev")), 4.5)


if __name__ == "__main__":
    unittest.main()
