"""
Minimal database migration runner (no external tooling).

Applies every migrations/*.sql file that hasn't been applied yet, in filename
order. Each file runs in its own transaction; applied versions are recorded in
the schema_migrations table so re-running is safe.

Usage:
    python migrate.py            # apply all pending migrations
"""

import os
import pathlib
import logging

import psycopg
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
MIGRATIONS_DIR = pathlib.Path(__file__).parent / "migrations"


def _applied_versions(cur) -> set[str]:
    """Ensure the tracking table exists and return the set of applied versions."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     TEXT PRIMARY KEY,
            applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    cur.execute("SELECT version FROM schema_migrations;")
    return {row[0] for row in cur.fetchall()}


def run_migrations():
    """Apply any migration files that have not been applied yet."""
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            done = _applied_versions(cur)
        conn.commit()

        pending = [p for p in files if p.name not in done]
        if not pending:
            logger.info("No pending migrations. Database up to date.")
            return

        for path in pending:
            version = path.name
            logger.info("Applying migration %s", version)
            sql = path.read_text(encoding="utf-8")
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s);",
                    (version,),
                )
            conn.commit()

    logger.info("Applied %d migration(s). Database up to date.", len(pending))


if __name__ == "__main__":
    run_migrations()
