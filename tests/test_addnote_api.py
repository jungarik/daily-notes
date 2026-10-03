"""`GET /api/addnote/{note_id}` — the note the editor opens with.

The section is a vertical like any other (`endpoints` → `helper` → `db`, its
own SQL, shared infra only), and this file pins the three things that are easy
to get wrong and invisible once it works:

* **Tenancy.** The owner predicate is in the query, not a check afterwards, so
  no path can forget it. A caller who does not own the note gets the same 404
  as one asking for a note that never existed — it must not become an oracle
  for which ids exist.
* **The nullable columns.** `text`, `path` and `tags` are nullable, and the
  client needs a value: the first two feed controlled React inputs (where
  `null` means uncontrolled — React warns and the field stops tracking its own
  state) and `tags` is rendered with `.map`, which throws on `null`. The
  coercion is three `or` expressions in the endpoint, so it is checked there.
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


class NullCoercionTests(unittest.TestCase):
    """`text`, `path` and `tags` are nullable in the database and must not
    arrive as `null` on the client.

    There is no mapper to unit-test: the coercion is three `or` expressions in
    the endpoint, beside the reads that produce the row. So these read the
    source — the question is whether each nullable column passes through one,
    and that is a property of the file. The schema's defaults are checked too,
    because a field that lost its `or` would otherwise be caught only by a
    note that happens to have a null column.
    """

    def test_every_nullable_column_is_coerced(self):
        for field in ("text", "path"):
            with self.subTest(field=field):
                self.assertIn(f'{field}=row["{field}"] or ""', ENDPOINTS_SOURCE)

        self.assertIn('tags=row["tags"] or []', ENDPOINTS_SOURCE)

    def test_the_schema_defaults_match_those_empties(self):
        """So a field left out entirely still cannot serialise as `null`."""
        source = (SECTION / "schemas.py").read_text(encoding="utf-8")

        self.assertIn('text: str = ""', source)
        self.assertIn('path: str = ""', source)
        self.assertIn("tags: list[str] = []", source)

    def test_the_row_is_not_spread_into_the_model(self):
        """`EditableNote(**row)` would hand the coercion to whatever the row
        happens to contain, and quietly carry a column nobody chose."""
        self.assertNotIn("EditableNote(**", ENDPOINTS_SOURCE)

    def test_no_mapper_was_left_behind(self):
        """The function this replaced. A dead `editable_note` would still be
        imported by nothing and read by everyone."""
        for path in SECTION.glob("*.py"):
            with self.subTest(file=path.name):
                self.assertNotIn("editable_note", path.read_text(encoding="utf-8"))


class AttachmentTests(unittest.TestCase):
    def test_each_attachment_gets_a_signed_proxy_url(self):
        """The bucket is private: the API reaches it, the browser does not. An
        `<img>` cannot send the initData header either, so the token in the
        URL is the auth."""
        views = helper.attachment_views([{"id": 7, "kind": "image", "mime": "image/jpeg"}])

        self.assertEqual(1, len(views))
        self.assertTrue(views[0]["url"].startswith("/api/notecard/attachments/7?t="))
        self.assertTrue(len(views[0]["url"].split("t=")[1]) > 10)

    def test_the_storage_key_never_reaches_the_client(self):
        """Not selected in SQL and not mapped. A bucket key in a payload is a
        key someone will try to fetch directly."""
        self.assertNotIn("storage_key", DB_SOURCE)
        self.assertNotIn("storage_key", (SECTION / "helper.py").read_text(encoding="utf-8"))

    def test_the_url_is_relative(self):
        """It resolves against whatever origin served the API to this browser;
        a baked-in host breaks the moment the API moves."""
        views = helper.attachment_views([{"id": 7, "kind": "image", "mime": "image/png"}])

        self.assertFalse(views[0]["url"].startswith("http"))

    def test_the_order_the_rows_arrive_in_is_kept(self):
        """Carousel order is the DB's `position, id`; re-sorting here would
        silently disagree with the feed."""
        rows = [{"id": 9, "kind": "image", "mime": "image/png"},
                {"id": 4, "kind": "image", "mime": "image/png"}]

        self.assertEqual([9, 4], [view["id"] for view in helper.attachment_views(rows)])

    def test_the_attachment_read_is_ordered_like_the_carousel(self):
        self.assertIn("ORDER BY position, id", DB_SOURCE)


class LinkedIdTests(unittest.TestCase):
    def test_both_directions_are_read(self):
        """Links are directed and backlinks are the reverse query, so a note's
        neighbours are the union — the set the card's chips already show."""
        self.assertIn("UNION", DB_SOURCE)
        self.assertIn("WHERE l.from_note_id = %s", DB_SOURCE)
        self.assertIn("WHERE l.to_note_id = %s", DB_SOURCE)

    def test_the_far_endpoint_is_owner_checked(self):
        """A link whose other side belongs to someone else must not leak that
        note's id — and the row is reachable, because this note's owner wrote
        the edge."""
        self.assertEqual(2, DB_SOURCE.count("n.user_id = %s"))

    def test_the_ids_come_back_sorted(self):
        """A stable payload: an unordered list makes a diff between two reads
        unreadable, and `UNION` promises no order."""
        self.assertIn("return sorted(", DB_SOURCE)


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

    def test_every_route_resolves_the_user_from_auth(self):
        """`current_user`, never a user id off the request — a browser must
        not be able to name whose notes it reads or writes. Counted against
        the number of routes, so a new one that takes the id from the client
        fails here instead of shipping."""
        routes = len(re.findall(r"@router\.(get|post|put|delete)\(", ENDPOINTS_SOURCE))
        resolved = ENDPOINTS_SOURCE.count("user_id: int = Depends(current_user)")

        self.assertEqual(routes, resolved)
        self.assertNotIn("user_id: int = Body", ENDPOINTS_SOURCE)
        self.assertNotIn("user_id: int = Query", ENDPOINTS_SOURCE)

    def test_the_select_is_narrow(self):
        """Only the columns the response carries — the row read is the note's
        own four fields, and nothing does `SELECT *`."""
        self.assertIn("SELECT id, text, path, tags FROM notes", DB_SOURCE)
        self.assertNotIn("SELECT *", DB_SOURCE)

    def test_the_follow_up_reads_happen_after_the_ownership_check(self):
        """An id that is not the caller's must never reach the links or
        attachments queries at all."""
        guard = ENDPOINTS_SOURCE.index("raise HTTPException(status_code=404")

        self.assertLess(guard, ENDPOINTS_SOURCE.index("db.attachments(note_id)"))
        self.assertLess(guard, ENDPOINTS_SOURCE.index("db.linked_note_ids("))


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
