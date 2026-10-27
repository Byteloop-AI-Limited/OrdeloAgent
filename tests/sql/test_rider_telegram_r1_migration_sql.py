"""The R1 migration (ordelo_datamodels/migrations/rider_telegram_r1.sql) run the way the owner will run it, on a SEPARATE
throwaway database whose rider_master has the PRE-R1 live shape (core/rider_master.sql before R1).

Proves: the pre-checks list duplicate / NULL / non-digit rider_ids and the status values; STEP 1 fails loudly (and changes
nothing) while duplicates remain; on clean data STEP 1 + the feature files (steps 2-5) apply, are repeatable, keep existing
rows and their dispatchability for status = 'active', and the VERIFY query reports 7 columns, 10 functions and the gate.
Local server only (the same guard as conftest.py); the database is dropped afterwards.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest

from .conftest import _GEN_RANDOM_BYTES_STUB, _PG_CRON_STUB, DATAMODELS, URI, _assert_local, sql_path

pytestmark = pytest.mark.skipif(not URI, reason="ORDELO_TEST_DB_URI not set (isolated Postgres required)")

DBNAME = "ordelo_r1_migration_test"
MIGRATION = (DATAMODELS / "migrations" / "rider_telegram_r1.sql").read_text()

# rider_master exactly as live had it before R1 (core/rider_master.sql, LIVE CHECK 2026-10-16), plus what the files need.
PRE_R1 = """
CREATE TABLE public.ordelo_config (config_key text PRIMARY KEY, config_value text, description text);
CREATE TABLE public.rider_master (
    id serial NOT NULL,
    rider_id character varying(12),
    rider_name text NOT NULL,
    vehicle_type character varying(15) NOT NULL,
    town character varying(255) NOT NULL,
    status character varying(50) NOT NULL,
    is_in_shift boolean NOT NULL DEFAULT TRUE,
    priority integer NOT NULL DEFAULT 1,
    dtts timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    shift_response_dtts timestamp without time zone,
    CONSTRAINT rider_master_pkey PRIMARY KEY (id)
);
CREATE TABLE public.delivery_dispatch (dispatch_id serial PRIMARY KEY, order_number varchar(100), rider_id varchar(12), vehicle_type varchar(15));
CREATE TABLE public.delivery_inflight (dispatch_id int PRIMARY KEY, order_number varchar(100), rider_id varchar(12));
CREATE TABLE public.food_order (order_id text PRIMARY KEY, order_number text UNIQUE);
CREATE TABLE public.order_item (id serial PRIMARY KEY, order_id text, product_name text);
INSERT INTO public.rider_master (rider_id, rider_name, vehicle_type, town, status, is_in_shift) VALUES
    ('447700900701', 'Ana', 'bike', 'Salisbury', 'active', true),
    ('447700900702', 'Ben', 'car', 'salisbury', 'inactive', false);
"""


def block(name: str) -> str:
    """The SQL between '-- ===== <name>' and the next '-- =====' marker."""
    m = re.search(rf"-- ===== {re.escape(name)}.*?\n(.*?)(?=\n-- =====|\Z)", MIGRATION, re.S)
    assert m, name
    return m.group(1)


@pytest.fixture
def mig():
    _assert_local(URI)
    admin = psycopg.connect(URI, autocommit=True)
    admin.execute(f"DROP DATABASE IF EXISTS {DBNAME} WITH (FORCE)")
    admin.execute(f"CREATE DATABASE {DBNAME}")
    parsed = urlparse(URI)
    conn = psycopg.connect(urlunparse(parsed._replace(path=f"/{DBNAME}")), autocommit=True)
    for role in ("anon", "authenticated", "service_role"):  # roles are cluster-wide; create them if this test runs first
        if not admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone():
            admin.execute(f"CREATE ROLE {role} NOLOGIN")
    conn.execute(PRE_R1)
    conn.execute(_GEN_RANDOM_BYTES_STUB)
    conn.execute(_PG_CRON_STUB)
    try:
        yield conn
    finally:
        conn.close()
        admin.execute(f"DROP DATABASE IF EXISTS {DBNAME} WITH (FORCE)")
        admin.close()


def apply_steps_1_to_5(conn):
    conn.execute(block("STEP 1"))
    conn.execute(sql_path("rider_master.sql").read_text())
    conn.execute(sql_path("auth_sessions.sql").read_text())  # current rider owner includes link-session revocation
    conn.execute(sql_path("pauses.sql").read_text())
    conn.execute(sql_path("t_rider_onboarding.sql").read_text())
    conn.execute((DATAMODELS / "ordering" / "order_has_test_item.sql").read_text())
    conn.execute(sql_path("job_create_dispatch.sql").read_text())


def test_prechecks_list_problems_and_step1_refuses_duplicates(mig):
    mig.execute("INSERT INTO public.rider_master (rider_id, rider_name, vehicle_type, town, status) VALUES"
                " ('447700900701', 'Ana again', 'bike', 'Salisbury', 'active'), (NULL, 'Nobody', 'bike', 'x', 'active'),"
                " ('RIDER01', 'Bad id', 'bike', 'x', 'Active')")
    dups = mig.execute(block("PRE-CHECK 1")).fetchall()
    assert [d[0] for d in dups] == ["447700900701"]
    bad = {r[1] for r in mig.execute(block("PRE-CHECK 2")).fetchall()}
    assert bad == {None, "RIDER01"}
    statuses = dict((r[0], r[1]) for r in mig.execute(block("PRE-CHECK 3")).fetchall())
    assert statuses == {"active": 3, "Active": 1, "inactive": 1}
    with pytest.raises(psycopg.errors.NotNullViolation):
        mig.execute(block("STEP 1"))
    # The failed block changed nothing (each statement stands alone; the first one failed).
    cols = {r[0] for r in mig.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'rider_master'")}
    assert "tuid" not in cols


def test_clean_data_migrates_and_verifies(mig):
    assert mig.execute(block("PRE-CHECK 1")).fetchall() == []
    assert mig.execute(block("PRE-CHECK 2")).fetchall() == []
    apply_steps_1_to_5(mig)
    apply_steps_1_to_5(mig)  # repeatable
    new_columns, functions, gate, dispatchable, choices = mig.execute(block("VERIFY (after step 5)")).fetchone()
    assert (new_columns, functions, gate, dispatchable) == (7, 10, True, 1)
    assert [t.lower() for t in choices["towns"]] == ["salisbury"] and choices["vehicle_types"] == ["bike", "car"]
    rows = mig.execute("SELECT rider_id, channel, tuid, phone_verified FROM public.rider_master ORDER BY rider_id").fetchall()
    assert rows == [("447700900701", "whatsapp", None, False), ("447700900702", "whatsapp", None, False)]
    # The existing active rider is still offered jobs; the inactive one is not.
    mig.execute("INSERT INTO public.food_order VALUES ('O1', 'MIG-1')")
    offered = {r[0] for r in mig.execute("SELECT rider_id FROM public.get_available_riders('MIG-1', 'SALISBURY', 'bike')")}
    assert offered == {"447700900701"}
    # And the onboarding functions work on the migrated table.
    out = mig.execute("SELECT public.t_rider_link(999000000701, 999000000701, '+447700900701', 'ana', 'Ana')").fetchone()[0]
    assert out["result"] == "linked"
