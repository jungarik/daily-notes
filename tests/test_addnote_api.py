"""`GET /api/addnote/{note_id}` — the note the editor opens with.

The section is a vertical like any other (`endpoints` → `helper` → `db`, its
own SQL, shared infra only), and this file pins the three things that are easy
to get wrong and invisible once it works:

* **Tenancy.** The owner predicate is in the query, not a check afterwards, so
  no path can forget it. A caller who does not own the note gets the same 404
  as one asking for a note that never existed — it must not become an oracle
  for which ids exist.
* **The null body.** `notes.text` is nullable and the textarea is a controlled
  React input, where `null` means "uncontrolled": React warns and the field
  stops tracking its own state. The mapper exists for that one conversion.
* **The surface.** One field beyond the id, matching the one control the page
  has wired. Selecting data for the disabled path/tags buttons would read as
  though they were live.
"""

import ast
import re
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SECTION = ROOT / "api" / "addnote"
DB_SOURCE = (SECTION / "db.py").read_text(encoding="utf-8")
ENDPOINTS_SOURCE = (SECTION / "endpoints.py").read_text(encoding="utf-8")
MAIN_SOURCE = (ROOT / "api" / "main.py").read_text(encoding="utf-8")


def _import_helper():
    """`api.addnote.helper`, with the modules its package pulls in put back.

    Same dance as `tests/test_path_picker.py`: `api.*.db` imports the shared
    psycopg pool at load and it is absent here, and a module left in
    `sys.modules` or on its package changes how other test files import.
    """
    stubbed = []

    if "db" not in sys.modules:
        stub = types.ModuleType("db")
        stub.cursor = lambda: None
        sys.modules["db"] = stub
        stubbed.append("db")

    try:
        from api.addnote import helper as imported
    finally:
        for name in stubbed:
            sys.modules.pop(name, None)

    import api.addnote as section

    for name in ("helper", "db"):
        sys.modules.pop("api.addnote." + name, None)

        if hasattr(section, name):
            delattr(section, name)

    return imported


helper = _import_helper()


class MapperTests(unittest.TestCase):
    def test_a_null_body_becomes_the_empty_string(self):
        """The reason this mapper exists. `null` into a controlled textarea
        makes React warn and the field stop tracking its own state."""
        self.assertEqual("", helper.editable_note({"id": 3, "text": None})["text"])

    def test_a_missing_key_is_treated_the_same(self):
        self.assertEqual("", helper.editable_note({"id": 3})["text"])

    def test_the_text_is_passed_through_untouched(self):
        """No trimming, no collapsing: this is the body the user is about to
        edit, and a stripped trailing newline is an edit they did not make."""
        body = "  line one\n\n  line two  \n"

        self.assertEqual(body, helper.editable_note({"id": 3, "text": body})["text"])

    def test_it_returns_only_what_the_page_has_wired(self):
        """The path/tags/reminder buttons are disabled; shipping their data
        would suggest otherwise."""
        shaped = helper.editable_note({"id": 3, "text": "x", "path": "Inbox",
                                       "tags": ["a"], "priority": "high"})

        self.assertEqual({"id", "text"}, set(shaped))

    def test_it_is_a_pure_mapper(self):
        """The endpoint is the impure boundary (api/README)."""
        row = {"id": 3, "text": "x"}

        self.assertEqual(helper.editable_note(row), helper.editable_note(row))
        self.assertEqual({"id": 3, "text": "x"}, row)


class TenancyTests(unittest.TestCase):
    def test_the_owner_predicate_is_in_the_query(self):
        """Not a check after the read. Without it any authenticated caller
        could read any note by guessing an id."""
        self.assertIn("WHERE id = %s AND user_id = %s", DB_SOURCE)

    def test_the_read_passes_both_ids(self):
        """A predicate with nothing bound to it is the same bug with extra
        SQL, so the call site is checked too."""
        self.assertIn("(note_id, user_id)", DB_SOURCE)

    def test_a_miss_is_a_404_not_a_403(self):
        """403 would confirm the note exists and belongs to someone else."""
        self.assertIn("status_code=404", ENDPOINTS_SOURCE)
        self.assertNotIn("403", ENDPOINTS_SOURCE)

    def test_the_endpoint_resolves_the_user_from_auth(self):
        """`current_user`, never a user id off the request — a browser must
        not be able to name whose notes it is reading."""
        self.assertIn("Depends(current_user)", ENDPOINTS_SOURCE)
        self.assertNotIn("user_id: int,", ENDPOINTS_SOURCE)

    def test_the_select_is_narrow(self):
        """Only the columns the response carries."""
        self.assertIn("SELECT id, text FROM notes", DB_SOURCE)


class SectionShapeTests(unittest.TestCase):
    def test_the_vertical_has_the_three_files(self):
        for name in ("endpoints.py", "helper.py", "db.py", "schemas.py"):
            with self.subTest(file=name):
                self.assertTrue((SECTION / name).exists())

    def test_it_imports_no_other_vertical(self):
        """The rule that keeps a section's logic from rippling into another's:
        shared infra only."""
        offending = []

        for path in SECTION.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))

            for node in ast.walk(tree):
                module = getattr(node, "module", None) or ""

                if module.startswith("api.") and not module.startswith("api.addnote"):
                    if module not in ("api.deps", "api.media_token"):
                        offending.append(f"{path.name}: {module}")

        self.assertEqual([], offending)

    def test_the_router_is_registered(self):
        """A section nobody includes is a 404 with a correct handler behind
        it — the same failure mode `test_cors_methods.py` guards."""
        self.assertIn("from api.addnote.endpoints import router as addnote_router",
                      MAIN_SOURCE)
        self.assertIn("app.include_router(addnote_router)", MAIN_SOURCE)

    def test_the_prefix_is_the_section_name(self):
        self.assertIn('prefix="/api/addnote"', ENDPOINTS_SOURCE)

    def test_the_get_verb_is_allowed_by_cors(self):
        """The Mini App is a separate origin; an unlisted verb is answered
        with 400 before the route is reached."""
        listed = re.search(r"allow_methods=\[([^\]]*)\]", MAIN_SOURCE).group(1)

        self.assertIn('"GET"', listed)


if __name__ == "__main__":
    unittest.main()
