"""Saving from the Add note page: `POST /api/addnote` and `PUT /…/{note_id}`.

Four things here are easy to get wrong and invisible once the happy path
works:

* **The chunks.** `note_chunks` is what search, RAG and the link suggestions
  match on. Text saved without rebuilding them is a note that reads correctly
  everywhere and cannot be found by what it now says, and nothing reports it.
* **The order of the two failures.** The row is written before the embedding
  round trip, and the chunks are built before the delete that replaces them.
  Both orders exist so that the thing that can fail cannot take the thing the
  user asked for with it.
* **The default path.** An empty path is not an error here — it is "wherever
  notes go", resolved from `config.DEFAULT_ROOT_FOLDER_KEY`. A note saved from
  this page always lands somewhere.
* **What a save must NOT touch.** `title`, `note_type` and `priority` are
  enrichment's, and the link graph belongs to a UI this page does not have.

`clean_tags` and `clean_root_path` run for real; the ordering and the column
list are read from source, because what matters is which statement comes first
and that is a property of the file.
"""

import importlib
import importlib.util
import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
SECTION = ROOT / "api" / "addnote"
DB_SOURCE = (SECTION / "db.py").read_text(encoding="utf-8")
HELPER_SOURCE = (SECTION / "helper.py").read_text(encoding="utf-8")
ENDPOINTS = (SECTION / "endpoints.py").read_text(encoding="utf-8")
SCHEMAS = (SECTION / "schemas.py").read_text(encoding="utf-8")
MAIN = (ROOT / "api" / "main.py").read_text(encoding="utf-8")

# The routes are executed below where FastAPI exists, and only read as source
# where it does not (`tests/test_cors_methods.py` makes the same allowance).
HAS_WEB = all(importlib.util.find_spec(name) is not None
              for name in ("fastapi", "pydantic"))


def _import_helper():
    """`api.addnote.helper` with everything it drags in put back — the same
    dance as `tests/test_path_picker.py`, for the same reason."""
    stubbed = []

    for name in ("db", "file_store", "psycopg"):
        if name not in sys.modules:
            stub = types.ModuleType(name)
            stub.cursor = lambda: None
            stub.types = types.ModuleType("psycopg.types")
            sys.modules[name] = stub
            stubbed.append(name)

    if "psycopg.types.json" not in sys.modules:
        json_stub = types.ModuleType("psycopg.types.json")
        json_stub.Json = lambda value: value
        sys.modules["psycopg.types.json"] = json_stub
        stubbed.append("psycopg.types.json")

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


class TagTests(unittest.TestCase):
    def test_blanks_and_whitespace_go(self):
        self.assertEqual(["work"], helper.clean_tags(["  work ", "", "   "]))

    def test_duplicates_collapse_case_insensitively(self):
        """Two tags that render identically would look like a bug in the
        card's tag line."""
        self.assertEqual(["Work"], helper.clean_tags(["Work", "work", "WORK"]))

    def test_the_first_spelling_wins(self):
        """The user typed "Work" first; silently lowercasing it is an edit
        they did not ask for."""
        self.assertEqual(["Work"], helper.clean_tags(["Work", "work"]))

    def test_the_users_order_is_kept(self):
        """Sorting would shuffle a list they just typed."""
        self.assertEqual(["zebra", "alpha"], helper.clean_tags(["zebra", "alpha"]))

    def test_the_cap_truncates_rather_than_refusing(self):
        """0–5 is the range enrichment produces. Losing the sixth tag beats
        failing the whole save over it."""
        tags = helper.clean_tags(["a", "b", "c", "d", "e", "f", "g"])

        self.assertEqual(5, len(tags))
        self.assertEqual(["a", "b", "c", "d", "e"], tags)

    def test_none_and_empty_are_safe(self):
        self.assertEqual([], helper.clean_tags(None))
        self.assertEqual([], helper.clean_tags([]))

    def test_it_is_pure(self):
        tags = ["a", "a", "b"]

        self.assertEqual(helper.clean_tags(tags), helper.clean_tags(tags))
        self.assertEqual(["a", "a", "b"], tags)


class PathTests(unittest.TestCase):
    def test_an_empty_path_becomes_the_default_root(self):
        """The behaviour the page depends on: a note saved here always lands
        somewhere, and nobody has to pick for that to be true."""
        import config
        import i18n

        self.assertEqual(i18n.t("en", config.DEFAULT_ROOT_FOLDER_KEY),
                         helper.clean_root_path("", "en"))

    def test_whitespace_counts_as_empty(self):
        self.assertEqual(helper.clean_root_path("", "en"),
                         helper.clean_root_path("   ", "en"))

    def test_the_default_follows_the_callers_language(self):
        self.assertNotEqual(helper.clean_root_path("", "en"),
                            helper.clean_root_path("", "uk"))

    def test_a_path_under_a_known_root_is_canonicalised(self):
        self.assertEqual("Inbox/today", helper.clean_root_path("inbox/today", "en"))

    def test_a_root_in_another_supported_language_is_accepted(self):
        """The locale decides what *empty* becomes, not what is valid: a user
        who switched languages still has paths in the old one."""
        self.assertIsNotNone(helper.clean_root_path("Вхідні/нотатки", "en"))

    def test_a_path_outside_every_root_is_rejected(self):
        """None, which the endpoint turns into a 422 — the vault's top level
        is a controlled vocabulary, not free text."""
        self.assertIsNone(helper.clean_root_path("Whatever/x", "en"))

    def test_traversal_segments_are_dropped(self):
        self.assertEqual("Inbox/x", helper.clean_root_path("Inbox/../x", "en"))

    def test_backslashes_are_normalised(self):
        self.assertEqual("Inbox/x", helper.clean_root_path("Inbox\\x", "en"))


def _routes():
    """`api.addnote.endpoints`, with psycopg stubbed so it imports."""
    installed = []

    for name, attributes in (
        ("psycopg", {"connect": lambda *a, **k: None}),
        ("psycopg.types", {}),
        ("psycopg.types.json", {"Json": lambda value: value}),
        ("psycopg_pool", {"ConnectionPool": object}),
    ):
        if name not in sys.modules:
            module = types.ModuleType(name)

            for key, value in attributes.items():
                setattr(module, key, value)

            sys.modules[name] = module
            installed.append(name)

    try:
        return importlib.import_module("api.addnote.endpoints"), installed
    except Exception:
        for name in installed:
            sys.modules.pop(name, None)
        raise


class FakeDb:
    """Records the calls the routes make, in order."""

    def __init__(self, owns=True):
        self.calls = []
        self.owns = owns
        self.chunks = "untouched"

    def get_language(self, user_id):
        return "en"

    def create_note(self, user_id, text, path, tags):
        self.calls.append(("create_note", text, path, tuple(tags)))

        return 7

    def update_note(self, user_id, note_id, text, path, tags):
        self.calls.append(("update_note", note_id, text, path, tuple(tags)))

        return self.owns

    def replace_chunks(self, note_id, chunks):
        self.calls.append(("replace_chunks", note_id, len(chunks)))
        self.chunks = chunks

    def note_for_user(self, user_id, note_id):
        return {"id": note_id, "text": "stored", "path": "Inbox", "tags": []}

    def attachments(self, note_id):
        return []

    def linked_note_ids(self, user_id, note_id):
        return []


@unittest.skipUnless(HAS_WEB, "fastapi/pydantic are not installed")
class ExecutedSaveTests(unittest.TestCase):
    """The save path **run**, not read.

    This class exists because of what the rest of this file missed: a
    `helper.rebuild_chunks` that called `db.replace_chunks` while importing no
    `db`. Every assertion around it compared strings in the source, and the one
    test that imported the module never called the function, so a guaranteed
    `NameError` shipped green. Reading a file tells you what it says; only
    calling it tells you it works.
    """

    def setUp(self):
        self.routes, self.installed = _routes()
        self.db = FakeDb()
        self.addCleanup(self._restore)
        patcher = patch.multiple(self.routes, db=self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _restore(self):
        for name in self.installed:
            sys.modules.pop(name, None)

        for name in list(sys.modules):
            if name.startswith("api.") or name == "db":
                sys.modules.pop(name, None)

    def _request(self, text="hello world", path="", tags=None):
        return types.SimpleNamespace(text=text, path=path, tags=tags or [])

    def test_create_writes_the_row_then_stores_the_chunks(self):
        with patch.object(self.routes.embedings, "build_chunks",
                          return_value=[{"index": 0}]):
            self.routes.create_note(self._request(), user_id=1)

        self.assertEqual(["create_note", "replace_chunks"],
                         [call[0] for call in self.db.calls])

    def test_an_empty_path_is_saved_as_the_default_root(self):
        import config
        import i18n

        with patch.object(self.routes.embedings, "build_chunks", return_value=[]):
            self.routes.create_note(self._request(path=""), user_id=1)

        self.assertEqual(i18n.t("en", config.DEFAULT_ROOT_FOLDER_KEY),
                         self.db.calls[0][2])

    def test_tags_are_cleaned_on_the_way_in(self):
        with patch.object(self.routes.embedings, "build_chunks", return_value=[]):
            self.routes.create_note(
                self._request(tags=[" a ", "A", "", "b", "c", "d", "e", "f"]),
                user_id=1)

        self.assertEqual(("a", "b", "c", "d", "e"), self.db.calls[0][3])

    def test_an_embedding_failure_keeps_the_note_and_skips_the_swap(self):
        """The note is already written. And `replace_chunks` must *not* run —
        the old chunks matching the old text beat no chunks at all."""
        with patch.object(self.routes.embedings, "build_chunks",
                          side_effect=RuntimeError("openai down")):
            self.routes.save_note(3, self._request(), user_id=1)

        self.assertEqual(["update_note"], [call[0] for call in self.db.calls])
        self.assertEqual("untouched", self.db.chunks)

    def test_an_edit_rebuilds_the_chunks(self):
        with patch.object(self.routes.embedings, "build_chunks",
                          return_value=[{"index": 0}, {"index": 1}]):
            self.routes.save_note(3, self._request(), user_id=1)

        self.assertEqual([("update_note", 3, "hello world", "Inbox", ()),
                          ("replace_chunks", 3, 2)], self.db.calls)

    def test_a_foreign_note_is_a_404_and_embeds_nothing(self):
        """The ownership miss has to short-circuit before the OpenAI call —
        otherwise a stranger's id costs an embedding."""
        from fastapi import HTTPException

        self.db.owns = False

        with patch.object(self.routes.embedings, "build_chunks") as embed:
            with self.assertRaises(HTTPException) as caught:
                self.routes.save_note(3, self._request(), user_id=1)

        self.assertEqual(404, caught.exception.status_code)
        embed.assert_not_called()

    def test_a_path_outside_every_root_is_422_and_writes_nothing(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as caught:
            self.routes.create_note(self._request(path="Nonsense/x"), user_id=1)

        self.assertEqual(422, caught.exception.status_code)
        self.assertEqual([], self.db.calls)


class ChunkRebuildTests(unittest.TestCase):
    def test_both_writes_rebuild_the_chunks(self):
        """Not only the edit: a created note with no chunks is invisible to
        search and RAG from birth."""
        self.assertEqual(2, ENDPOINTS.count("embedings.build_chunks(text)"))
        self.assertEqual(2, ENDPOINTS.count("db.replace_chunks(note_id, chunks)"))

    def test_the_chunks_are_built_before_the_table_is_touched(self):
        """The embedding round trip is the part that fails. Deleting first and
        failing to insert leaves the note invisible to search, which is worse
        than leaving it matching its old wording."""
        for route in ("def create_note", "def save_note"):
            with self.subTest(route=route):
                body = ENDPOINTS[ENDPOINTS.index(route):]
                body = body[:body.index("return _saved")]

                self.assertLess(body.index("embedings.build_chunks"),
                                body.index("db.replace_chunks"))

    def test_the_helper_touches_no_database(self):
        """It had a `db.replace_chunks` call and no `db` import — a NameError
        waiting for the first save. The I/O belongs to the routes, and a
        module that is not allowed to reach for the database cannot make that
        mistake again."""
        self.assertNotIn("db.", HELPER_SOURCE[HELPER_SOURCE.index("def "):])
        # The function itself, not the docstring that explains why it went.
        self.assertNotIn("def rebuild_chunks", HELPER_SOURCE)
        self.assertNotIn("helper.rebuild_chunks(", ENDPOINTS)

    def test_the_swap_only_runs_when_the_build_succeeded(self):
        """`else:` on the `try`, not a line after it: on failure the old
        chunks stay, because chunks matching the old text beat none at all."""
        for route in ("def create_note", "def save_note"):
            with self.subTest(route=route):
                body = ENDPOINTS[ENDPOINTS.index(route):]
                body = body[:body.index("return _saved")]

                self.assertLess(body.index("except Exception:"),
                                body.index("db.replace_chunks"))
                self.assertIn("else:", body)

    def test_the_swap_is_one_transaction(self):
        """A delete that commits without its insert is the same bug by
        another route, so both statements share one `cursor()`."""
        body = DB_SOURCE[DB_SOURCE.index("def replace_chunks"):]

        self.assertEqual(1, body.count("with cursor() as cur:"))
        self.assertLess(body.index("DELETE FROM note_chunks"),
                        body.index("INSERT INTO note_chunks"))

    def test_an_embedding_failure_does_not_fail_the_save(self):
        """The note is already written by then. Reporting an error would tell
        the user their text did not save when it did."""
        self.assertEqual(2, ENDPOINTS.count("except Exception:"))
        self.assertEqual(2, ENDPOINTS.count("logger.exception("))

    def test_the_note_is_written_before_the_embedding_runs(self):
        """Same argument, one level up: the text is what the user asked to
        keep, so the row lands first and a failed embedding costs only
        searchability."""
        for route, write in (("def create_note", "db.create_note("),
                             ("def save_note", "db.update_note(")):
            with self.subTest(route=route):
                body = ENDPOINTS[ENDPOINTS.index(route):]
                body = body[:body.index("return _saved")]

                self.assertLess(body.index(write),
                                body.index("embedings.build_chunks"))


class WhatASaveMustNotTouchTests(unittest.TestCase):
    def test_the_update_writes_only_the_editors_three_fields(self):
        """`title`, `note_type` and `priority` belong to enrichment; blanking
        them here would undo work the user asked an agent for."""
        body = DB_SOURCE[DB_SOURCE.index("def update_note"):]
        statement = body[body.index("UPDATE notes"):body.index("RETURNING")]

        self.assertIn("SET text = %s, path = %s, tags = %s", statement)
        for column in ("title", "note_type", "priority", "source_type"):
            with self.subTest(column=column):
                self.assertNotIn(column, statement)

    def test_the_link_graph_is_left_alone(self):
        """The page displays a note's neighbours and offers no way to change
        them. A save that rewrote the graph from a read-only list would be the
        worst kind of surprise."""
        # The docstring explains the absence, so the check is against the
        # model's fields rather than the whole class.
        fields = SCHEMAS[SCHEMAS.index('    text: str = Field'):]

        self.assertNotIn("linked_note_ids", fields)
        self.assertNotIn("attachments", fields)
        self.assertNotIn("note_links", DB_SOURCE[DB_SOURCE.index("def update_note"):])

    def test_a_created_note_is_left_untitled(self):
        """`title` is an LLM's one-line summary — a title the user never wrote
        would be a guess presented as theirs. Every section already falls back
        to a text snippet when it is absent."""
        body = DB_SOURCE[DB_SOURCE.index("def create_note"):]
        statement = body[body.index("INSERT INTO notes"):body.index("RETURNING")]

        self.assertIn("(user_id, text, source_type, path, tags)", statement)
        self.assertNotIn("title", statement)

    def test_every_section_can_display_an_untitled_note(self):
        """The claim the decision above rests on, checked rather than assumed:
        each read vertical maps an absent title to a text snippet."""
        for section in ("feed", "explorer", "notesheet", "mapview", "search"):
            with self.subTest(section=section):
                source = (ROOT / "api" / section / "helper.py").read_text(encoding="utf-8")

                self.assertIn("_display_title", source)


class TenancyTests(unittest.TestCase):
    def test_the_update_is_owner_scoped_in_the_statement(self):
        body = DB_SOURCE[DB_SOURCE.index("def update_note"):]

        self.assertIn("WHERE id = %s AND user_id = %s RETURNING id;", body)

    def test_a_foreign_note_is_a_404(self):
        """The update's miss *is* the ownership check, so the route cannot
        forget it."""
        body = ENDPOINTS[ENDPOINTS.index("def save_note"):]

        self.assertIn("if not db.update_note(", body)
        self.assertIn("status_code=404", body)

    def test_the_created_note_belongs_to_the_caller(self):
        body = DB_SOURCE[DB_SOURCE.index("def create_note"):]

        self.assertIn("(user_id, text", body)


class ResponseTests(unittest.TestCase):
    def test_a_save_answers_with_the_stored_note(self):
        """Read back, not echoed: the path sent is not the path stored — an
        empty one became the default root, a typed one was normalised — and a
        client trusting its own input would show the wrong folder."""
        self.assertIn("def _saved(", ENDPOINTS)
        self.assertIn("db.note_for_user(user_id, note_id)",
                      ENDPOINTS[ENDPOINTS.index("def _saved("):])
        self.assertEqual(2, ENDPOINTS.count("return _saved(user_id, note_id)"))

    def test_create_answers_201(self):
        self.assertIn("status_code=201", ENDPOINTS)

    def test_the_text_is_required_and_bounded(self):
        """An empty note is nothing, and an unbounded body is an embedding
        bill with no ceiling."""
        body = SCHEMAS[SCHEMAS.index("class SaveNoteRequest"):]

        self.assertIn("min_length=1", body)
        self.assertIn("max_length=20000", body)

    def test_put_is_allowed_by_cors(self):
        """A new verb on the API. `CORSMiddleware` answers an unlisted
        method's preflight with 400 *before* the route is reached — the Mini
        App is a separate origin, so this is how a correct handler ships
        dead."""
        listed = re.search(r"allow_methods=\[([^\]]*)\]", MAIN).group(1)

        self.assertIn('"PUT"', listed)


if __name__ == "__main__":
    unittest.main()
