"""Exercise rider offer checkpoints and reference swaps on isolated Postgres."""
import json
import pytest
from .conftest import fetch_one

pytestmark = pytest.mark.usefixtures('sql_env')


@pytest.fixture(autouse=True)
def setup(db):
    db.execute('TRUNCATE public.rider_offer_alert, public.delivery_dispatch, public.delivery_inflight, public.delivery_summary, public.rider_master, public.http_calls CASCADE')
    db.execute("UPDATE public.http_stub_status SET status=200")
    db.execute("INSERT INTO public.ordelo_config(config_key, config_value) VALUES ('RIDER_OFFER_ALERT_OFFSETS_SECS','10,20,30,45,60,90,120'), ('ORDELO_APP_URL','https://example.test') ON CONFLICT (config_key) DO UPDATE SET config_value=excluded.config_value")
    db.execute("INSERT INTO public.delivery_summary(order_number,status,pickup_time) VALUES ('STRK-TEST-1','unassigned',now())")
    db.execute("INSERT INTO public.rider_master(rider_id,rider_name,channel,tuid,tcid) VALUES ('RIDER01','Rider','telegram',101,101), ('RIDER02','Other','telegram',102,102)")
    db.execute("INSERT INTO public.delivery_dispatch(order_number,rider_id,status,dtts,channel_msg_ref) VALUES ('STRK-TEST-1','RIDER01','unassigned',now() - interval '25 seconds','tg:101:1')")


def val(db, sql, args=()):
    return fetch_one(db, sql, args)


def test_snapshot_swap_and_stale(db):
    did = val(db, 'SELECT dispatch_id FROM public.delivery_dispatch')
    snap = val(db, 'SELECT public.rider_offer_reminder_snapshot(%s)', (did,))
    assert snap['state'] == 'open' and snap['msg_ref'] == 'tg:101:1'
    assert set(snap['offer']) == {'dispatch_id','order_number','rider_id','rider_payout','vehicle_type','distance','pickup_time','rest_name','rest_address','customer_name','customer_address'}
    swap = val(db, 'SELECT public.rider_offer_reminder_sent(%s,%s,%s)', (did, 'tg:101:2', 'tg:101:1'))
    assert swap['result'] == 'swapped' and swap['previous_ref'] == 'tg:101:1'
    assert val(db, 'SELECT public.rider_offer_reminder_sent(%s,%s,%s)', (did, 'tg:101:3', 'tg:101:1'))['result'] == 'stale'
    db.execute('DELETE FROM public.delivery_dispatch')
    assert val(db, 'SELECT public.rider_offer_reminder_sent(%s,%s,%s)', (did, 'tg:101:4', 'tg:101:2'))['result'] == 'gone'


def test_seed_collapse_accept_and_escalation(db):
    assert val(db, 'SELECT public.job_rider_offer_alerts()')
    rows = db.execute("SELECT offset_secs,status FROM public.rider_offer_alert WHERE kind='reminder' ORDER BY offset_secs").fetchall()
    assert rows[:3] == [(10, 'superseded'), (20, 'sent'), (30, 'pending')]
    payload = json.loads(val(db, 'SELECT body FROM public.http_calls ORDER BY id DESC LIMIT 1'))
    assert payload['reminders'][0]['n'] == 2
    db.execute("INSERT INTO public.delivery_dispatch(order_number,rider_id,status) VALUES ('STRK-TEST-1','RIDER02','accepted')")
    did = val(db, "SELECT dispatch_id FROM public.delivery_dispatch WHERE rider_id='RIDER01'")
    assert val(db, 'SELECT public.rider_offer_state(%s)', (did,)) == {'state':'quiet','reason':'accepted_elsewhere'}
    db.execute('SELECT public.job_rider_offer_alerts()')
    assert val(db, "SELECT count(*) FROM public.rider_offer_alert WHERE status='pending'") == 0


def test_post_failure_keeps_pending_and_blank_cancels(db):
    db.execute('UPDATE public.http_stub_status SET status=500')
    assert not val(db, 'SELECT public.job_rider_offer_alerts()')
    assert val(db, "SELECT count(*) FROM public.rider_offer_alert WHERE status='pending'") == 8
    db.execute("UPDATE public.ordelo_config SET config_value='' WHERE config_key='RIDER_OFFER_ALERT_OFFSETS_SECS'")
    db.execute('SELECT public.job_rider_offer_alerts()')
    assert val(db, "SELECT count(*) FROM public.rider_offer_alert WHERE status='pending'") == 0


def test_service_grants_and_migration_repeatable(db):
    from pathlib import Path
    from .conftest import ROOT
    migration = (ROOT / 'ordelo_datamodels/migrations/rider_offer_alerts.sql').read_text()
    start = migration.index('-- ===== STEP 1: TABLE')
    end = migration.index('-- ===== STEP 4: VERIFY')
    db.execute(migration[start:end])
    db.execute(migration[start:end])
    r2 = (ROOT / "ordelo_datamodels/migrations/rider_offer_alerts_r2.sql").read_text()
    db.execute(r2[r2.index("-- ===== STEP 1: COLUMNS"):r2.index("-- ===== STEP 3: VERIFY")])
    assert val(db, "SELECT to_regclass('public.rider_offer_alert_reminder_cycle_uidx') IS NOT NULL")
    assert val(db, "SELECT to_regclass('public.rider_offer_alert_reminder_uidx') IS NULL")
    assert val(db, "SELECT has_function_privilege('service_role','public.rider_offer_reminder_snapshot(integer)','execute')")
    assert not val(db, "SELECT has_function_privilege('anon','public.rider_offer_reminder_snapshot(integer)','execute')")
    assert val(db, "SELECT has_table_privilege('service_role','public.rider_offer_alert','select,insert,update')")


def test_gate_and_eligibility(db):
    did = val(db, 'SELECT dispatch_id FROM public.delivery_dispatch')
    for statement, reason in [
        ("UPDATE public.rider_master SET is_in_shift=false WHERE rider_id='RIDER01'", 'off_shift'),
        ("UPDATE public.rider_master SET is_in_shift=true, status='inactive' WHERE rider_id='RIDER01'", 'inactive'),
        ("UPDATE public.rider_master SET status='active', tcid=NULL, tuid=NULL WHERE rider_id='RIDER01'", 'no_chat'),
    ]:
        db.execute(statement)
        assert val(db, 'SELECT public.rider_offer_state(%s)', (did,))['reason'] == reason
    db.execute("UPDATE public.rider_master SET tcid=101,tuid=101 WHERE rider_id='RIDER01'")
    db.execute("UPDATE public.delivery_dispatch SET status='declined' WHERE dispatch_id=%s", (did,))
    assert val(db, 'SELECT public.rider_offer_state(%s)', (did,)) == {'state':'closed','reason':'declined'}


def test_concurrent_swaps_choose_one(db):
    from concurrent.futures import ThreadPoolExecutor
    from .conftest import _connect
    did = val(db, 'SELECT dispatch_id FROM public.delivery_dispatch')

    def swap(ref):
        with _connect() as conn:
            return conn.execute('SELECT public.rider_offer_reminder_sent(%s,%s,%s)', (did, ref, 'tg:101:1')).fetchone()[0]['result']

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(swap, ['tg:101:2', 'tg:101:3']))
    assert sorted(results) == ['stale', 'swapped']


def test_declines_restart_open_offers_and_do_not_move_escalation(db):
    db.execute("INSERT INTO public.delivery_dispatch(order_number,rider_id,status,dtts) VALUES ('STRK-TEST-1','RIDER02','unassigned', now() - interval '25 seconds')")
    db.execute('SELECT public.job_rider_offer_alerts()')
    did = val(db, "SELECT dispatch_id FROM public.delivery_dispatch WHERE rider_id='RIDER01'")
    due = val(db, "SELECT due_at FROM public.rider_offer_alert WHERE kind='escalation'")
    db.execute("UPDATE public.delivery_dispatch SET status='declined' WHERE rider_id='RIDER02'")
    db.execute('SELECT public.job_rider_offer_alerts()')
    assert val(db, "SELECT count(*) FROM public.rider_offer_alert WHERE dispatch_id=%s AND cycle=0 AND status='superseded'", (did,)) == 6
    assert val(db, "SELECT count(*) FROM public.rider_offer_alert WHERE dispatch_id=%s AND cycle=1 AND status='pending' AND due_at >= now()", (did,)) == 7
    assert val(db, "SELECT count(*) FROM public.rider_offer_alert WHERE rider_id='RIDER02' AND status='pending'") == 0
    assert val(db, "SELECT due_at FROM public.rider_offer_alert WHERE kind='escalation'") == due
    db.execute("UPDATE public.rider_offer_alert SET due_at=now()-interval '1 second' WHERE dispatch_id=%s AND cycle=1 AND offset_secs=10", (did,))
    db.execute('SELECT public.job_rider_offer_alerts()')
    assert json.loads(val(db, 'SELECT body FROM public.http_calls ORDER BY id DESC LIMIT 1'))['reminders'][0]['n'] == 1
    db.execute("INSERT INTO public.delivery_dispatch(order_number,rider_id,status) VALUES ('STRK-TEST-1','RIDER02','declined')")
    db.execute('SELECT public.job_rider_offer_alerts()')
    assert val(db, "SELECT count(*) FROM public.rider_offer_alert WHERE dispatch_id=%s AND cycle=2 AND status='pending'", (did,)) == 7
    db.execute("DELETE FROM public.delivery_dispatch WHERE rider_id='RIDER02'")
    db.execute('SELECT public.job_rider_offer_alerts()')
    assert val(db, "SELECT max(cycle) FROM public.rider_offer_alert WHERE dispatch_id=%s", (did,)) == 2


def test_accept_then_decline_restarts(db):
    db.execute("INSERT INTO public.delivery_dispatch(order_number,rider_id,status) VALUES ('STRK-TEST-1','RIDER02','unassigned')")
    db.execute('SELECT public.job_rider_offer_alerts()')
    db.execute("UPDATE public.delivery_dispatch SET status='accepted' WHERE rider_id='RIDER02'")
    db.execute('SELECT public.job_rider_offer_alerts()')
    db.execute("UPDATE public.delivery_dispatch SET status='declined' WHERE rider_id='RIDER02'")
    db.execute('SELECT public.job_rider_offer_alerts()')
    assert val(db, "SELECT count(*) FROM public.rider_offer_alert WHERE rider_id='RIDER01' AND cycle=1 AND status='pending'") == 7


def test_redispatch_escalation_is_per_round(db):
    db.execute('SELECT public.job_rider_offer_alerts()')
    db.execute("UPDATE public.delivery_summary SET status='assigned' WHERE order_number='STRK-TEST-1'")
    db.execute('SELECT public.job_rider_offer_alerts()')
    assert val(db, "SELECT status FROM public.rider_offer_alert WHERE kind='escalation'") == 'cancelled'
    db.execute("DELETE FROM public.delivery_dispatch")
    db.execute("UPDATE public.delivery_summary SET status='unassigned', redispatch_dtts=now()-interval '2 minutes 1 second' WHERE order_number='STRK-TEST-1'")
    db.execute("INSERT INTO public.delivery_dispatch(order_number,rider_id,status,dtts) VALUES ('STRK-TEST-1','RIDER01','unassigned',now()-interval '2 minutes')")
    db.execute('SELECT public.job_rider_offer_alerts()')
    assert val(db, "SELECT count(*) FROM public.rider_offer_alert WHERE kind='escalation'") == 2
    payload = json.loads(val(db, 'SELECT body FROM public.http_calls ORDER BY id DESC LIMIT 1'))
    assert payload['escalations'] == [{'order_number': 'STRK-TEST-1', 'after_secs': 120, 'redispatched': True, 'offered': 1, 'declined': 0}]
