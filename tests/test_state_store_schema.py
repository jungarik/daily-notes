"""The turn tree's SQL against the table it actually queries.

`tests/test_broker.py` drives the loop with a fake store, so nothing there ever
compares `state_store.py` to `agent_states`. That gap shipped a `SELECT` naming
an `error` column the migration never created — which only fired on the confirm
path, after a write had already succeeded.

Both files are read as text, so this runs with no database and no psycopg.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
TABLE = "agent_states"


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


def _read_selected_columns() -> set[str]:
    """Every bare column name the store's SELECTs ask `agent_states` for."""
    source = (ROOT / "agents" / "broker" / "state_store.py").read_text(encoding="utf-8")
    selected = set()

    for clause in re.findall(r"SELECT(.+?)FROM\s+" + TABLE, source, re.S | re.I):
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

    def test_the_store_selects_nothing_the_table_does_not_have(self):
        missing = _read_selected_columns() - _read_columns()

        self.assertEqual(set(), missing, f"agent_states has no {sorted(missing)}")

    def test_the_insert_names_only_real_columns(self):
        source = (ROOT / "agents" / "broker" / "state_store.py").read_text(encoding="utf-8")
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
        source = (ROOT / "agents" / "broker" / "state_store.py").read_text(encoding="utf-8")
        rebuild = source.split("def read_history", 1)[1]

        self.assertNotIn("error=", rebuild)


if __name__ == "__main__":
    unittest.main()
