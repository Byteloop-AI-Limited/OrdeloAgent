"""The R2-R4 migration (ordelo_datamodels/migrations/rider_telegram_r2_r4.sql) run the way the owner will run it, on a SEPARATE
throwaway database in the state live is in today: the pre-R1 tables with migrations/rider_telegram_r1.sql steps 1-5 applied.

Proves: the pre-checks report R1 in place and the open legacy rider threads; STEP 1 + the feature files (steps 2-3) apply and
are repeatable; existing offers read 'whatsapp'; new offers are stamped with the rider's channel; a thread opened before R2
('ORDELO-<uuid>') is still found and is closed when the rider's next job opens its dispatch thread; VERIFY reports 3 / 1 / 6.
Local server only (the same guard as conftest.py); the database is dropped afterwards.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest

from .conftest import _GEN_RANDOM_BYTES_STUB, _PG_CRON_STUB, DATAMODELS, URI, _assert_local, sql_path

pytestmark = pytest.mark.skipif(not URI, reason="ORDELO_TEST_DB_URI not set (isolated Postgres required)")

DBNAME = "ordelo_r2_r4_migration_test"
R1 = (DATAMODELS / "migrations" / "rider_telegram_r1.sql").read_text()
MIGRATION = (DATAMODELS / "migrations" / "rider_telegram_r2_r4.sql").read_text()

# The live shape before R1 (the R1 migration test uses the same), plus an offer and a rider thread opened before R2.
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
CREATE TABLE public.delivery_dispatch (
    dispatch_id serial NOT NULL, order_number character varying(100) NOT NULL, rider_id character varying(12) NOT NULL,
    rider_payout double precision NOT NULL DEFAULT 5, vehicle_type character varying(15) NOT NULL DEFAULT 'bike',
    distance double precision NOT NULL DEFAULT 1, status character varying(50) NOT NULL DEFAULT 'unassigned',
    status_update_dtts timestamp without time zone, reason_for_decline text, dt date NOT NULL DEFAULT CURRENT_DATE,
    dtts timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP, paid_status character varying(20) NOT NULL DEFAULT 'unpaid',
    paid_dtts timestamp without time zone, CONSTRAINT delivery_dispatch_pkey PRIMARY KEY (dispatch_id));
CREATE TABLE public.delivery_detail (order_number varchar(100), vehicle_type varchar(15));
CREATE TABLE public.delivery_summary (order_number varchar(100) PRIMARY KEY, pickup_time timestamptz, rest_id text,
    rest_name text, rest_lon float, rest_lat float, rest_address text, town text, customer_id text, customer_name text,
    customer_lon float, customer_lat float, customer_address text);
CREATE TABLE public.thread (thread_id text PRIMARY KEY, agent text, recipient varchar(12), is_active boolean,
    retain_thread boolean DEFAULT false, dt date DEFAULT current_date, dtts timestamp DEFAULT current_timestamp,
    last_access_dtts timestamp DEFAULT current_timestamp);
CREATE TYPE public.http_response AS (status int, content_type text, headers text, content text);
CREATE FUNCTION public.http_post(uri text, content text, content_type text) RETURNS public.http_response
    LANGUAGE sql AS $$ SELECT ROW(200, 'application/json', NULL, '{}')::public.http_response $$;
-- an offer and its rider thread that exist before this migration (sent on WhatsApp, thread id 'ORDELO-<uuid>')
INSERT INTO public.thread (thread_id, agent, recipient, is_active) VALUES ('ORDELO-6f1c-legacy', 'ORDELO', '447700900701', TRUE);
INSERT INTO public.delivery_dispatch (order_number, rider_id) VALUES ('OLD-1', '447700900701');
CREATE TABLE public.delivery_inflight (dispatch_id int PRIMARY KEY, order_number varchar(100), rider_id varchar(12));
CREATE TABLE public.food_order (order_id text PRIMARY KEY, order_number text UNIQUE);
CREATE TABLE public.order_item (id serial PRIMARY KEY, order_id text, product_name text);
INSERT INTO public.rider_master (rider_id, rider_name, vehicle_type, town, status, is_in_shift) VALUES
    ('447700900701', 'Ana', 'bike', 'Salisbury', 'active', true),
    ('447700900702', 'Ben', 'car', 'salisbury', 'inactive', false);
"""




def block(sql: str, name: str) -> str:
    """The SQL between '-- ===== <name>' and the next '-- =====' marker."""
    m = re.search(rf"-- ===== {re.escape(name)}.*?\n(.*?)(?=\n-- =====|\Z)", sql, re.S)
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
    for role in ("anon", "authenticated"):  # roles are cluster-wide; create them if this test runs first
        if not admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone():
            admin.execute(f"CREATE ROLE {role} NOLOGIN")
    conn.execute(PRE_R1)
    conn.execute(_GEN_RANDOM_BYTES_STUB)
    conn.execute(_PG_CRON_STUB)
    apply_r1(conn)  # what the owner ran on 2026-10-22
    try:
        yield conn
    finally:
        conn.close()
        admin.execute(f"DROP DATABASE IF EXISTS {DBNAME} WITH (FORCE)")
        admin.close()


def apply_r1(conn):
    conn.execute(block(R1, "STEP 1"))
    conn.execute(sql_path("rider_master.sql").read_text())
    conn.execute(sql_path("pauses.sql").read_text())
    conn.execute(sql_path("t_rider_onboarding.sql").read_text())
    conn.execute((DATAMODELS / "ordering" / "order_has_test_item.sql").read_text())
    conn.execute(sql_path("job_create_dispatch.sql").read_text())


def apply_steps_1_to_3(conn):
    conn.execute(block(MIGRATION, "STEP 1"))
    conn.execute(sql_path("delivery_dispatch.sql").read_text())
    conn.execute(sql_path("rider_threads.sql").read_text())


def test_prechecks_report_r1_and_the_open_legacy_threads(mig):
    assert mig.execute(block(MIGRATION, "PRE-CHECK 1")).fetchone() == (True, True)
    assert [r[0] for r in mig.execute(block(MIGRATION, "PRE-CHECK 2")).fetchall()] == ["ORDELO-6f1c-legacy"]


def test_steps_apply_repeatably_and_verify(mig):
    apply_steps_1_to_3(mig)
    apply_steps_1_to_3(mig)  # repeatable
    assert mig.execute(block(MIGRATION, "VERIFY")).fetchone() == (3, 1, 6, 0)
    # The offer that existed before the migration reads 'whatsapp' (how it was sent); the statement trigger still fires once.
    assert mig.execute("SELECT channel, channel_msg_ref, thread_id FROM public.delivery_dispatch WHERE order_number = 'OLD-1'"
                       ).fetchone() == ("whatsapp", None, None)
    triggers = {r[0] for r in mig.execute("SELECT tgname FROM pg_trigger WHERE tgrelid = 'public.delivery_dispatch'::regclass"
                                          " AND NOT tgisinternal")}
    assert triggers == {"trigger_delivery_dispatch_whook", "trigger_delivery_dispatch_stamp_channel"}


def test_new_offers_take_the_riders_channel_and_threads_follow_dispatches(mig):
    apply_steps_1_to_3(mig)
    mig.execute("SELECT public.t_rider_link(999000000701, 999000000701, '447700900701', 'ana', 'Ana')")
    mig.execute("INSERT INTO public.delivery_dispatch (order_number, rider_id) VALUES ('NEW-1', '447700900701'), ('NEW-2', '447700900702')")
    rows = dict(mig.execute("SELECT order_number, channel FROM public.delivery_dispatch WHERE order_number LIKE 'NEW-%'").fetchall())
    assert rows == {"NEW-1": "telegram", "NEW-2": "whatsapp"}
    # Before the rider's next assignment, the legacy thread is still their open thread (dispatch fields empty, WhatsApp).
    legacy = mig.execute("SELECT public.rider_thread_active('ORDELO', '447700900701', false)").fetchone()[0]
    assert (legacy["thread_id"], legacy["dispatch_id"], legacy["channel"]) == ("ORDELO-6f1c-legacy", None, "whatsapp")
    did = mig.execute("SELECT dispatch_id FROM public.delivery_dispatch WHERE order_number = 'NEW-1'").fetchone()[0]
    out = mig.execute("SELECT public.rider_thread_open('ORDELO', '447700900701', %s)", (did,)).fetchone()[0]
    assert out == {"result": "opened", "thread_id": f"ORDELO-dispatch-{did}", "closed": ["ORDELO-6f1c-legacy"]}
    snap = mig.execute("SELECT public.rider_thread_active('ORDELO', '447700900701', true)").fetchone()[0]
    assert (snap["result"], snap["dispatch_id"], snap["channel"], snap["tcid"]) == ("active", did, "telegram", 999000000701)
