"""The R5-R6 migration (ordelo_datamodels/migrations/rider_telegram_r5_r6.sql) run the way the owner will run it, on a SEPARATE
throwaway database in the state live is in after R2-R4: the feature files as applied so far, the location table with its
two-value source CHECK, a Telegram rider switched off by the daily shift question, and no pause sweep job.

Proves: the pre-checks report R1-R4 in place and list who STEP 2 changes; STEP 1 lets 'telegram_current' in; STEP 2 switches
Telegram riders on and only them; STEP 3 applies exactly the files the migration lists, in its order, twice (repeatable);
VERIFY reports true / 7 / true / true / 4 / 0; VERIFY 2 is 0 before step 6 and 1 after. Local server only (same guard as
conftest.py); the database is dropped afterwards.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest

from .conftest import (
    _GEN_RANDOM_BYTES_STUB,
    _PG_CRON_STUB,
    DATAMODELS,
    HERE,
    MIGRATION_FILES,
    URI,
    _assert_local,
    migration_sql,
    sql_path,
)

pytestmark = pytest.mark.skipif(not URI, reason="ORDELO_TEST_DB_URI not set (isolated Postgres required)")

DBNAME = "ordelo_r5_r6_migration_test"
MIGRATION = (DATAMODELS / "migrations" / "rider_telegram_r5_r6.sql").read_text()
NEW_IN_R5_R6 = {"rider_shift.sql", "enquire_shift_availability.sql", "t_admin_pauses.sql", "wa_location.sql", "job_pause_sweep.sql"}
OLD_SOURCE_CHECK = ("CHECK (((source)::text = ANY ((ARRAY['whatsapp_current'::character varying, "
                    "'restaurant_confirmation'::character varying])::text[])))")


def block(sql: str, name: str) -> str:
    """The SQL between '-- ===== <name>' and the next '-- =====' marker."""
    m = re.search(rf"-- ===== {re.escape(name)}.*?\n(.*?)(?=\n-- =====|\Z)", sql, re.S)
    assert m, name
    return m.group(1)


def step3_files() -> list[str]:
    """The files STEP 3 of the HOW TO APPLY comment lists, in its order."""
    text = MIGRATION[MIGRATION.index("STEP 3"):MIGRATION.index("STEP 4")]
    return re.findall(r"ordelo_datamodels/(\S+\.sql)", text)


@pytest.fixture
def mig():
    _assert_local(URI)
    admin = psycopg.connect(URI, autocommit=True)
    admin.execute(f"DROP DATABASE IF EXISTS {DBNAME} WITH (FORCE)")
    admin.execute(f"CREATE DATABASE {DBNAME}")
    for role in ("anon", "authenticated"):
        if not admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone():
            admin.execute(f"CREATE ROLE {role} NOLOGIN")
    conn = psycopg.connect(urlunparse(urlparse(URI)._replace(path=f"/{DBNAME}")), autocommit=True)
    conn.execute("SET TIME ZONE 'UTC'")
    conn.execute(_GEN_RANDOM_BYTES_STUB)
    conn.execute(_PG_CRON_STUB)
    conn.execute((HERE / "minimal_schema.sql").read_text())
    for name in MIGRATION_FILES:
        if name not in NEW_IN_R5_R6:
            conn.execute(migration_sql(name))
    # The location tables as live has them: the feature file, then the CHECK put back to its two values.
    conn.execute(sql_path("wa_location.sql").read_text())
    conn.execute("ALTER TABLE public.wa_location_observation DROP CONSTRAINT wa_location_observation_source_check")
    conn.execute(f"ALTER TABLE public.wa_location_observation ADD CONSTRAINT wa_location_observation_source_check {OLD_SOURCE_CHECK}")
    conn.execute("INSERT INTO public.rider_master (rider_id, rider_name, status, is_in_shift, channel, tuid, tcid) VALUES"
                 " ('447700900951', 'Tess', 'active', false, 'telegram', 51, 51),"
                 " ('447700900952', 'Will', 'active', false, 'whatsapp', NULL, NULL)")
    conn.execute("INSERT INTO public.delivery_summary (order_number) VALUES ('ELAS-LOC-1')")
    conn.execute("INSERT INTO public.delivery_dispatch (order_number, rider_id, status) VALUES ('ELAS-LOC-1', '447700900951', 'assigned')")
    try:
        yield conn
    finally:
        conn.close()
        admin.execute(f"DROP DATABASE IF EXISTS {DBNAME} WITH (FORCE)")
        admin.close()


def observe(conn, source):
    conn.execute("INSERT INTO public.wa_location_observation (order_number, dispatch_id, rider_id, latitude, longitude, source,"
                 " observed_at) SELECT 'ELAS-LOC-1', dispatch_id, rider_id, 51.07, -1.79, %s, now()"
                 " FROM public.delivery_dispatch WHERE order_number = 'ELAS-LOC-1'", (source,))


def test_step3_lists_the_r5_r6_feature_files_in_a_working_order():
    assert step3_files() == ["availability/pauses.sql", "availability/rider_shift.sql", "dispatch/enquire_shift_availability.sql",
                             "telegram/t_order_alerts.sql", "restaurant_admin/restaurant_ready_adjust_notices.sql",
                             "telegram/t_admin_pauses.sql"]


def test_prechecks(mig):
    assert mig.execute(block(MIGRATION, "PRE-CHECK 1")).fetchone() == (True, True, True)
    assert mig.execute(block(MIGRATION, "PRE-CHECK 2")).fetchall() == [("447700900951", "Tess", "active", False)]
    assert ("ELAS", "Elas Kitchen", 0) in mig.execute(block(MIGRATION, "PRE-CHECK 3")).fetchall()
    assert mig.execute(block(MIGRATION, "PRE-CHECK 4")).fetchall() == []


def test_steps_apply_repeatably_and_verify(mig):
    with pytest.raises(psycopg.errors.CheckViolation):
        observe(mig, "telegram_current")
    for _ in range(2):  # every step is safe to re-run
        mig.execute(block(MIGRATION, "STEP 1"))
        mig.execute(block(MIGRATION, "STEP 2"))
        for rel in step3_files():
            mig.execute((DATAMODELS / rel).read_text())
    observe(mig, "telegram_current")
    observe(mig, "whatsapp_current")
    shifts = dict(mig.execute("SELECT rider_id, is_in_shift FROM public.rider_master WHERE rider_id LIKE '44770090095%'").fetchall())
    assert shifts == {"447700900951": True, "447700900952": False}  # Telegram riders only
    assert mig.execute(block(MIGRATION, "VERIFY")).fetchone() == (True, 7, True, True, 4, 0)
    assert mig.execute(block(MIGRATION, "VERIFY 2")).fetchone() == (0,)
    mig.execute(sql_path("job_pause_sweep.sql").read_text())  # STEP 6, after the deploy
    assert mig.execute(block(MIGRATION, "VERIFY 2")).fetchone() == (1,)


def test_step2_reports_who_it_switched_on(mig):
    assert mig.execute(block(MIGRATION, "STEP 2")).fetchall() == [("447700900951", "Tess", "active")]
    assert mig.execute(block(MIGRATION, "STEP 2")).fetchall() == []
