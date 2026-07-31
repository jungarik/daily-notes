"""Shared database access — one place that knows how to open a connection."""

from contextlib import contextmanager

import psycopg

import config


@contextmanager
def cursor():
    """Yield a cursor inside a transaction; commit on success, rollback on error.

    Usage:
        with cursor() as cur:
            cur.execute(...)
    """
    with psycopg.connect(config.DATABASE_URL) as conn:
        with conn.cursor() as cur:
            yield cur
