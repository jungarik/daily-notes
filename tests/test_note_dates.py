"""A note's created and modified dates: the column, the formatter, the payload,
and the rows the Add-note info block shows.

`created_at` has been on `notes` since the first migration; `updated_at` is
new (0023). The trigger's behaviour was checked against a real Postgres when it
was written — backfill, no-op writes, a changed row, a jsonb change — and what
is pinned here is the shape that makes that behaviour hold: the backfill runs
*before* the trigger exists (otherwise every old note would read as modified at
the moment of the migration), the trigger fires on every UPDATE, and it only
bumps a row that actually changed.

The formatter runs under node against the real module; the page's wiring is
read from source, as the rest of the page's structure is.
"""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
MIGRATIONS = ROOT / "migrations"
MIGRATION = (MIGRATIONS / "0023_note_updated_at.sql").read_text(encoding="utf-8")
FORMAT_JS = ROOT / "browser" / "webapp" / "src" / "lib" / "format.js"
PAGE = (ROOT / "browser" / "webapp" / "src" / "components" / "AddNote.jsx").read_text(encoding="utf-8")
ENDPOINTS = (ROOT / "api" / "addnote" / "endpoints.py").read_text(encoding="utf-8")
DB_SOURCE = (ROOT / "api" / "addnote" / "db.py").read_text(encoding="utf-8")
SCHEMAS = (ROOT / "api" / "addnote" / "schemas.py").read_text(encoding="utf-8")


class MigrationTests(unittest.TestCase):
    def test_it_is_the_newest_migration(self):
        """Migrations are append-only and applied in filename order."""
        names = sorted(path.name for path in MIGRATIONS.glob("*.sql"))

        self.assertEqual("0023_note_updated_at.sql", names[-1])

    def test_the_column_defaults_to_now_and_is_never_null(self):
        self.assertIn(
            "ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()",
            MIGRATION)

    def test_existing_notes_are_backfilled_to_their_creation_time(self):
        """Earlier edits were never recorded, so 'not changed since created' is
        the honest value — not the moment the migration ran."""
        self.assertIn("UPDATE notes SET updated_at = created_at;", MIGRATION)

    def test_the_backfill_runs_before_the_trigger_exists(self):
        """Otherwise the trigger would stamp every backfilled row with now()."""
        self.assertLess(MIGRATION.index("UPDATE notes SET updated_at = created_at;"),
                        MIGRATION.index("CREATE TRIGGER"))

    def test_every_update_goes_through_the_trigger(self):
        """Nine UPDATE statements across six files write to `notes`; a trigger
        is the one place that sees all of them."""
        self.assertIn("BEFORE UPDATE ON notes", MIGRATION)
        self.assertIn("FOR EACH ROW", MIGRATION)

    def test_only_a_changed_row_is_bumped(self):
        """An editor save that writes back identical text, path and tags is not
        a modification."""
        self.assertIn("IF NEW IS DISTINCT FROM OLD THEN", MIGRATION)
        self.assertIn("NEW.updated_at = now();", MIGRATION)

    def test_re_applying_is_safe(self):
        self.assertIn("DROP TRIGGER IF EXISTS notes_touch_updated_at ON notes;", MIGRATION)
        self.assertIn("CREATE OR REPLACE FUNCTION", MIGRATION)


class PayloadTests(unittest.TestCase):
    def test_the_note_read_selects_both_timestamps(self):
        self.assertIn("SELECT id, text, path, tags, created_at, updated_at FROM notes", DB_SOURCE)

    def test_the_payload_carries_the_dates_and_the_users_zone(self):
        for field in ("created_at: datetime | None", "updated_at: datetime | None",
                      "timezone: str | None"):
            with self.subTest(field=field):
                self.assertIn(field, SCHEMAS)

    def test_both_builders_fill_them_in(self):
        """The note read and the save's read-back share one shape."""
        self.assertEqual(2, ENDPOINTS.count('created_at=row["created_at"]'))
        self.assertEqual(2, ENDPOINTS.count('updated_at=row["updated_at"]'))
        self.assertEqual(2, ENDPOINTS.count("timezone=db.get_timezone(user_id)"))

    def test_the_timezone_read_is_a_plain_users_lookup(self):
        body = DB_SOURCE[DB_SOURCE.index("def get_timezone"):].split("\ndef ", 1)[0]

        self.assertIn("SELECT timezone FROM users WHERE id = %s;", body)


SCRIPT = """
import { fmtDateTime } from %s;
const [iso, zone, locale] = JSON.parse(process.argv[2]);
console.log(JSON.stringify(fmtDateTime(iso, zone, locale)));
"""


def _format(iso, zone=None, locale="en-GB"):
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "fmt.mjs"
        script.write_text(SCRIPT % json.dumps(FORMAT_JS.as_posix()), encoding="utf-8")
        out = subprocess.run(["node", str(script), json.dumps([iso, zone, locale])],
                             capture_output=True, text=True, check=True)

    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node is not available")
class FormatterTests(unittest.TestCase):
    def test_the_instant_is_shown_on_the_users_clock(self):
        """11:32 UTC is 14:32 in Kyiv in October (UTC+3)."""
        self.assertEqual("16 Oct 2026, 14:32", _format("2026-10-16T11:32:00Z", "Europe/Kyiv"))

    def test_another_zone_gives_another_time(self):
        self.assertEqual("16 Oct 2026, 11:32", _format("2026-10-16T11:32:00Z", "UTC"))

    def test_a_zone_the_engine_rejects_falls_back_instead_of_throwing(self):
        """A bad saved value must cost the zone, never the date."""
        self.assertRegex(_format("2026-10-16T11:32:00Z", "Not/AZone"), r"^16 Oct 2026, \d\d:\d\d$")

    def test_no_zone_is_the_devices(self):
        self.assertRegex(_format("2026-10-16T11:32:00Z", None), r"^16 Oct 2026, \d\d:\d\d$")

    def test_a_missing_or_unparseable_date_is_empty(self):
        self.assertEqual("", _format(None))
        self.assertEqual("", _format("not a date"))


class InfoRowsTests(unittest.TestCase):
    def test_the_dates_sit_above_the_path(self):
        rows = PAGE[PAGE.index("const infoRows = ["):]

        self.assertLess(rows.index('key: "created"'), rows.index('key: "modified"'))
        self.assertLess(rows.index('key: "modified"'), rows.index('key: "path"'))

    def test_each_date_has_its_own_glyph(self):
        self.assertIn('{ key: "created", icon: <CalendarGlyph />', PAGE)
        self.assertIn('{ key: "modified", icon: <ModifiedGlyph />', PAGE)

    def test_the_dates_exist_only_for_a_saved_note(self):
        """A new note has neither yet, so the rows are not shown at all."""
        self.assertIn("const dated = note !== null && !!note.created_at;", PAGE)
        self.assertIn("...(dated ? [", PAGE)

    def test_the_dates_use_the_formatter_with_the_users_zone(self):
        self.assertIn("fmtDateTime(note.created_at, note.timezone)", PAGE)
        self.assertIn("fmtDateTime(note.updated_at, note.timezone)", PAGE)

    def test_the_glyphs_share_one_decorative_svg(self):
        """Same stroke recipe as every glyph, and hidden from assistive tech —
        the text beside each says what it is."""
        self.assertEqual(1, len(re.findall(r'<svg aria-hidden="true"', PAGE)))
        self.assertIn("function Glyph(", PAGE)
        for name in ("FolderGlyph", "CalendarGlyph", "ModifiedGlyph"):
            with self.subTest(glyph=name):
                self.assertIn(f"function {name}()", PAGE)


if __name__ == "__main__":
    unittest.main()
