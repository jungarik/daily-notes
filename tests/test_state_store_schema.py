"""Every reader of `agent_states` against the migration that creates it.

Four modules query this one table: the loop's own store, and the three
duplicated `read_state` backings — one per vertical that may read a peer's hop.
The duplication is deliberate (`db.py` is per-vertical by design), which is
exactly why the guard is not: four copies of a `SELECT` are four chances to
drift, and a drifted one fails at the point an agent reads a peer's state, long
after the row was written.

That is not hypothetical. A `SELECT` naming an `error` column the migration
never created shipped once, and only fired on the confirm path — after a write
had already succeeded. `tests/test_loop.py` could not have caught it: it drives
the loop with a fake store, so nothing there ever compares SQL to schema.

Everything is read as text, so this runs with no database and no psycopg.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
TABLE = "agent_states"

# Every module holding SQL against the turn tree. `test_no_reader_is_missing`
# keeps this honest — a fifth copy fails there before it can fail in production.
READERS = (
    "agents/runtime/state_store.py",
    "tools/classifier/db.py",
    "tools/enricher/db.py",
    "tools/reminder/db.py",
    "tools/responder/db.py",
)


def _read_columns() -> set[str]:
    """The column names `agent_states` is created with."""
    migration = (ROOT / "migrations" / "0022_agent_states.sql").read_text(encoding="utf-8")
    body = migration.split(f"CREATE TABLE IF NOT EXISTS {TABLE}", 1)[1]
    body = body.split(");", 1)[0]

    found = set()

    for line in body.splitlines():
        stripped = line.strip()

        if not stripped or stripped.startswith(("(", ")", "--")):
            continue

        name = stripped.split()[0]

        if name.upper() in {"PRIMARY", "FOREIGN", "CONSTRAINT", "CHECK", "UNIQUE"}:
            continue

        found.add(name.lower())

    return found


def _find_selected_columns(source: str) -> set[str]:
    """Every bare column name this source's SELECTs ask `agent_states` for.

    Takes the text, not a path: the caller owns the read, so a test can hand
    this a literal and see what the parser makes of it.

    The clause may hold no `SELECT` or `FROM` of its own, which is what keeps a
    vertical's other queries out: `db.py` selects from half a dozen tables, and
    a span that swallowed them would report `notes` columns as missing ones.
    """
    between = r"((?:(?!\bSELECT\b|\bFROM\b).)*)"
    selected = set()

    for clause in re.findall(r"\bSELECT\b" + between + r"\bFROM\s+" + TABLE,
                             source, re.S | re.I):
        clause = re.sub(r"DISTINCT ON \([^)]*\)", " ", clause, flags=re.I)

        for column in clause.split(","):
            column = column.strip().lower()

            if re.fullmatch(r"[a-z_][a-z0-9_]*", column):
                selected.add(column)

    return selected


class ColumnTests(unittest.TestCase):
    def test_the_migration_parses_into_the_columns_we_expect(self):
        """If this fails the other assertions are meaningless — the parser has
        drifted from the migration's shape, not the code from the schema."""
        columns = _read_columns()

        self.assertIn("state_id", columns)
        self.assertIn("correlation_id", columns)
        self.assertIn("state", columns)

    def test_every_reader_selects_nothing_the_table_does_not_have(self):
        columns = _read_columns()

        for reader in READERS:
            source = (ROOT / reader).read_text(encoding="utf-8")
            missing = _find_selected_columns(source) - columns

            with self.subTest(reader=reader):
                self.assertEqual(set(), missing, f"agent_states has no {sorted(missing)}")

    def test_every_reader_asks_for_something(self):
        """A reader whose SQL the parser cannot see is a reader this file only
        appears to guard — the assertion above would pass on an empty set."""
        for reader in READERS:
            source = (ROOT / reader).read_text(encoding="utf-8")

            with self.subTest(reader=reader):
                self.assertNotEqual(set(), _find_selected_columns(source))

    def test_no_reader_is_missing(self):
        """`READERS` is the whole list, not the list someone remembered.

        A vertical that gains `read_state` gains a fourth copy of this SELECT,
        and an unlisted copy is an unguarded one.

        Only the Python packages are walked. `rglob` from the repo root spends
        twenty seconds in the Mini App's `node_modules` to find nothing."""
        sources = [path for package in ("agents", "api", "tools", "capture", "common")
                   for path in (ROOT / package).rglob("*.py")]
        found = {
            str(path.relative_to(ROOT)).replace("\\", "/")
            for path in sources
            if re.search(r"\bFROM\s+" + TABLE, path.read_text(encoding="utf-8"), re.I)
        }

        self.assertEqual(set(READERS), found)

    def test_the_insert_names_only_real_columns(self):
        source = (ROOT / "agents" / "runtime" / "state_store.py").read_text(encoding="utf-8")
        clause = source.split(f"INSERT INTO {TABLE}", 1)[1].split(")", 1)[0]
        inserted = {
            name.strip().lower()
            for name in clause.replace("(", " ").split(",")
            if name.strip()
        }

        self.assertEqual(set(), inserted - _read_columns())


class EntryTests(unittest.TestCase):
    def test_the_rebuilt_entry_reports_no_error(self):
        """`error` is not stored, so the rebuild must not claim one. Left in the
        SELECT it was a crash; left in the row mapping it would be a lie."""
        source = (ROOT / "agents" / "runtime" / "state_store.py").read_text(encoding="utf-8")
        rebuild = source.split("def read_history", 1)[1]

        self.assertNotIn("error=", rebuild)


if __name__ == "__main__":
    unittest.main()
