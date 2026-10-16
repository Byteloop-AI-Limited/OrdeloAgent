"""Isolated-database fixtures for the SQL tests (migrations in ordelo_datamodels/migrations).

These tests run the real migration files against a THROWAWAY Postgres and are skipped unless
ORDELO_TEST_DB_URI is set. They reset the `public` schema, so they refuse to run against anything that
is not a local server (host localhost/127.0.0.1/::1 or a unix-socket directory). Never point this at the
shared Supabase database; preparing SQL does not authorise applying it (database-operations skill).

    ORDELO_TEST_DB_URI=postgresql://postgres@localhost:5432/postgres pytest tests/sql -q
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

URI = os.environ.get("ORDELO_TEST_DB_URI")
ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "ordelo_datamodels" / "migrations"
HERE = Path(__file__).parent

pytestmark = pytest.mark.skipif(not URI, reason="ORDELO_TEST_DB_URI not set (isolated Postgres required)")


def _assert_local(uri: str) -> None:
    parsed = urlparse(uri)
    host = parsed.hostname or parse_qs(parsed.query).get("host", [""])[0]
    if host not in ("localhost", "127.0.0.1", "::1") and not host.startswith("/"):
        raise RuntimeError(f"ORDELO_TEST_DB_URI must be a local throwaway database, got host {host!r}")


def pytest_collection_modifyitems(config, items):
    skip = pytest.mark.skip(reason="ORDELO_TEST_DB_URI not set (isolated Postgres required)")
    for item in items:
        if "tests/sql" in str(item.fspath).replace("\\", "/") and not URI:
            item.add_marker(skip)


def _connect(autocommit: bool = True):
    import psycopg

    conn = psycopg.connect(URI, autocommit=autocommit)
    conn.execute("SET TIME ZONE 'UTC'")  # tests compare ISO strings; do not depend on the server or PGTZ
    return conn


# Migrations are applied in this order (each file is idempotent). Extended as phases are added.
MIGRATION_FILES = [
    "create_t_inbox.sql",
    "create_t_invites.sql",
    "restaurant_order_decision.sql",
    "create_t_order_alerts.sql",
    "restaurant_ready_adjust_notices.sql",
]

# The embedded test server has no pgcrypto. create_t_invites.sql needs gen_random_bytes() (invite codes) only,
# so that one statement is removed and a stand-in function is created in the `extensions` schema. Nothing else
# in any migration is altered before it runs.
_PGCRYPTO_STATEMENT = "CREATE EXTENSION IF NOT EXISTS pgcrypto;"
_GEN_RANDOM_BYTES_STUB = """
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE OR REPLACE FUNCTION extensions.gen_random_bytes(n int) RETURNS bytea LANGUAGE sql VOLATILE AS $$
    SELECT decode(substr(md5(random()::text || clock_timestamp()::text), 1, n * 2), 'hex')
$$;
"""


def migration_sql(name: str) -> str:
    text = (MIGRATIONS / name).read_text()
    if _PGCRYPTO_STATEMENT in text:
        text = text.replace(_PGCRYPTO_STATEMENT, "")
    return text


@pytest.fixture(scope="session")
def sql_env():
    """Reset the public schema, create the Supabase-style roles, minimal tables, then every migration."""
    _assert_local(URI)
    with _connect() as conn:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")
        for role in ("anon", "authenticated"):
            conn.execute(
                f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') "
                f"THEN CREATE ROLE {role} NOLOGIN; END IF; END $$"
            )
            conn.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
        conn.execute(_GEN_RANDOM_BYTES_STUB)
        conn.execute((HERE / "minimal_schema.sql").read_text())
        for name in MIGRATION_FILES:
            conn.execute(migration_sql(name))
    return URI


@pytest.fixture
def db(sql_env):
    """A fresh autocommit connection."""
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


def fetch_one(conn, sql: str, params=None):
    return conn.execute(sql, params or ()).fetchone()[0]
