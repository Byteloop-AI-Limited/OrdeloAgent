"""Isolated-database fixtures for the SQL tests (the SQL files under ordelo_datamodels/: telegram/, restaurant_admin/, migrations/).

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
DATAMODELS = ROOT / "ordelo_datamodels"
MIGRATIONS = DATAMODELS / "migrations"


def sql_path(name: str) -> Path:
    """The one file called `name` anywhere under ordelo_datamodels/ (feature folders: telegram/, restaurant_admin/, migrations/)."""
    found = [p for p in DATAMODELS.rglob(name) if not {"archive", "_archive", "migrations"} & set(p.parts)]
    if len(found) != 1:
        raise FileNotFoundError(f"{name}: expected exactly one file under ordelo_datamodels/, found {found}")
    return found[0]
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
    "t_inbox.sql",
    "t_sent_messages.sql",
    "t_invites.sql",
    "restaurant_order_decision.sql",
    # pauses.sql (rider bot R1) comes before t_order_alerts.sql since R6: t_alert_destinations() (a SQL function, checked
    # when created) calls is_paused(). On live pauses.sql has been applied since 22 Oct.
    "pauses.sql",
    "t_order_alerts.sql",
    "restaurant_ready_adjust_notices.sql",
    "t_housekeeping.sql",
    # Rider bot phase R1 (plans/telegram-rider-bot-plan.md): rider_master is created in its target shape by minimal_schema.sql.
    "rider_master.sql",
    "t_rider_onboarding.sql",
    "job_pause_sweep.sql",
    # Rider bot phases R2-R4: thread per dispatch (the thread table itself comes from minimal_schema.sql).
    "rider_threads.sql",
    # Rider bot phases R5-R6: shift rule, WhatsApp-only shift question, admin pauses, Telegram location source.
    "rider_shift.sql",
    "enquire_shift_availability.sql",
    "t_admin_pauses.sql",
    "wa_location.sql",
]


def dispatch_channel_trigger_sql() -> str:
    """Only the channel-stamping row trigger from dispatch/delivery_dispatch.sql (R2-R4).

    The rest of that file (the statement trigger that POSTs every offer) is left out on purpose: other SQL tests insert
    delivery_dispatch rows and must not see extra http_calls.
    """
    text = sql_path("delivery_dispatch.sql").read_text()
    start = text.index("CREATE OR REPLACE FUNCTION public.delivery_dispatch_stamp_channel")
    end = text.index("EXECUTE FUNCTION delivery_dispatch_stamp_channel ();") + len("EXECUTE FUNCTION delivery_dispatch_stamp_channel ();")
    return text[start:end]

# The embedded test server has no pgcrypto. t_invites.sql needs gen_random_bytes() (invite codes) only,
# so that one statement is removed and a stand-in function is created in the `extensions` schema. Nothing else
# in any migration is altered before it runs.
_PGCRYPTO_STATEMENT = "CREATE EXTENSION IF NOT EXISTS pgcrypto;"
_GEN_RANDOM_BYTES_STUB = """
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE OR REPLACE FUNCTION extensions.gen_random_bytes(n int) RETURNS bytea LANGUAGE sql VOLATILE AS $$
    SELECT decode(substr(md5(random()::text || clock_timestamp()::text), 1, n * 2), 'hex')
$$;
"""

# The files under ordelo_datamodels/ schedule their own pg_cron jobs (SQL standard rule 1). The test server has no
# pg_cron, so a stand-in cron.schedule()/cron.unschedule() records the calls in cron.job and does nothing else.
_PG_CRON_STUB = """
CREATE SCHEMA IF NOT EXISTS cron;
CREATE TABLE IF NOT EXISTS cron.job (jobname text PRIMARY KEY, schedule text NOT NULL, command text NOT NULL);
CREATE OR REPLACE FUNCTION cron.schedule(p_jobname text, p_schedule text, p_command text) RETURNS bigint LANGUAGE sql AS $$
    INSERT INTO cron.job VALUES (p_jobname, p_schedule, p_command)
    ON CONFLICT (jobname) DO UPDATE SET schedule = EXCLUDED.schedule, command = EXCLUDED.command
    RETURNING 1::bigint
$$;
CREATE OR REPLACE FUNCTION cron.unschedule(p_jobname text) RETURNS boolean LANGUAGE sql AS $$
    WITH d AS (DELETE FROM cron.job WHERE jobname = p_jobname RETURNING 1) SELECT EXISTS (SELECT 1 FROM d)
$$;
"""


def migration_sql(name: str) -> str:
    text = sql_path(name).read_text()
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
        conn.execute("DROP SCHEMA IF EXISTS cron CASCADE")
        conn.execute(_PG_CRON_STUB)
        conn.execute((HERE / "minimal_schema.sql").read_text())
        for name in MIGRATION_FILES:
            conn.execute(migration_sql(name))
        conn.execute(dispatch_channel_trigger_sql())
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
