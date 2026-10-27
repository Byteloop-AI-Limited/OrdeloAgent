"""Apply r3 twice to r2-era rows in a separate disposable database."""
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest

from .conftest import URI, ROOT, HERE, _PG_CRON_STUB, _GEN_RANDOM_BYTES_STUB, _assert_local, sql_path

pytestmark = pytest.mark.skipif(not URI, reason='isolated PostgreSQL required')


def test_r3_repeatable_upgrade_preserves_r2_rows_and_grants():
    _assert_local(URI)
    dbname = 'ordelo_offer_r3_migration_test'
    admin = psycopg.connect(URI, autocommit=True)
    admin.execute(f'DROP DATABASE IF EXISTS {dbname} WITH (FORCE)')
    admin.execute(f'CREATE DATABASE {dbname}')
    conn = psycopg.connect(urlunparse(urlparse(URI)._replace(path=f'/{dbname}')), autocommit=True)
    try:
        conn.execute(_GEN_RANDOM_BYTES_STUB)
        conn.execute(_PG_CRON_STUB)
        conn.execute((HERE / 'minimal_schema.sql').read_text())
        for role in ('anon', 'authenticated', 'service_role'):
            admin.execute(f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN CREATE ROLE {role} NOLOGIN; END IF; END $$")
        conn.execute(sql_path('pauses.sql').read_text())
        r1 = (ROOT / 'ordelo_datamodels/migrations/rider_offer_alerts.sql').read_text()
        conn.execute(r1[r1.index('-- ===== STEP 1: TABLE'):r1.index('-- ===== STEP 4: VERIFY')])
        conn.execute("INSERT INTO public.delivery_summary(order_number,status,pickup_time) VALUES ('STRK-TEST-1','unassigned',now())")
        conn.execute("INSERT INTO public.rider_master(rider_id,rider_name,channel,tuid,tcid) VALUES ('RIDER01','One','telegram',1,1),('RIDER02','Two','telegram',2,2)")
        conn.execute("INSERT INTO public.delivery_dispatch(order_number,rider_id,status,channel,dtts) VALUES ('STRK-TEST-1','RIDER01','unassigned','telegram',now()-interval '5 seconds'),('STRK-TEST-1','RIDER02','declined','telegram',now()-interval '5 seconds')")
        conn.execute('SELECT public.job_rider_offer_alerts()')
        assert conn.execute("SELECT count(*) FROM public.rider_offer_alert WHERE kind='reminder'").fetchone()[0] == 7
        r2 = (ROOT / 'ordelo_datamodels/migrations/rider_offer_alerts_r2.sql').read_text()
        upgrade = r2[r2.index('-- ===== STEP 1: COLUMNS'):r2.index('-- ===== STEP 3: VERIFY')]
        conn.execute(upgrade)
        conn.execute(upgrade)
        assert conn.execute("SELECT DISTINCT cycle FROM public.rider_offer_alert WHERE kind='reminder'").fetchall() == [(1,)]
        conn.execute('SELECT public.job_rider_offer_alerts()')
        assert conn.execute("SELECT count(*) FROM public.rider_offer_alert WHERE kind='reminder'").fetchone()[0] == 7
        before = conn.execute("SELECT id, cycle, due_at, status FROM public.rider_offer_alert ORDER BY id").fetchall()
        assert any(row[1] > 0 for row in before)
        r3 = (ROOT / 'ordelo_datamodels/migrations/rider_offer_alerts_r3.sql').read_text()
        upgrade = r3[r3.index('-- ===== STEP 1:'):r3.index('-- ===== STEP 3:')]
        conn.execute(upgrade)
        conn.execute(upgrade)
        verify = r3[r3.index('SELECT\n', r3.index('-- ===== STEP 3: VERIFY')):]
        assert conn.execute(verify).fetchone() == (True, False)
        assert conn.execute("SELECT id, cycle, due_at, status FROM public.rider_offer_alert ORDER BY id").fetchall() == before
        assert conn.execute("SELECT has_function_privilege('service_role','public.job_rider_offer_alerts()','execute')").fetchone()[0]
        for role in ('anon', 'authenticated', 'public'):
            assert not conn.execute("SELECT has_function_privilege(%s,'public.job_rider_offer_alerts()','execute')", (role,)).fetchone()[0]
    finally:
        conn.close()
        admin.execute(f'DROP DATABASE IF EXISTS {dbname} WITH (FORCE)')
        admin.close()
