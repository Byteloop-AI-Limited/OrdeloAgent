"""Real rider dashboard RPC contracts on the dedicated disposable database; no live state."""
import json
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from .conftest import URI, fetch_one, sql_path

pytestmark = pytest.mark.usefixtures("sql_env")
RIDER, OTHER = "447700900891", "447700900892"
TOKEN, COOKIE, UA = "a" * 64, "b" * 64, "c" * 64


@pytest.fixture(autouse=True)
def setup(db):
    db.execute("DELETE FROM auth_sessions WHERE principal_id IN (%s,%s)", (RIDER, OTHER))
    db.execute("DELETE FROM delivery_dispatch WHERE rider_id IN (%s,%s)", (RIDER, OTHER))
    db.execute("DELETE FROM rider_master WHERE rider_id IN (%s,%s)", (RIDER, OTHER))
    db.execute("DELETE FROM rider_registrations WHERE phone=%s", ("+"+RIDER,))
    for rid, tuid in ((RIDER, 891), (OTHER, 892)):
        db.execute("INSERT INTO rider_master(rider_id,rider_name,town,vehicle_type,status,tuid,tcid,phone_verified,t_linked_at) VALUES(%s,'Rider','London','bike','inactive',%s,%s,true,clock_timestamp())", (rid,tuid,tuid))


def mint(db, actor=891, token=TOKEN):
    return fetch_one(db, "SELECT rider_dashboard_mint(%s,%s)", (actor,token))


def activate(db, token=TOKEN, cookie=COOKIE):
    return fetch_one(db, "SELECT rider_dashboard_activate(%s,%s,%s)", (token,cookie,UA))


def session(db):
    assert mint(db)["result"] == "ok"
    assert activate(db)["result"] == "ok"


def jobs(db, tab="completed", **kwargs):
    args = [COOKIE, UA, tab, kwargs.get("start", "2026-10-01") if tab == "completed" else None,
            kwargs.get("end", "2026-10-31") if tab == "completed" else None,
            kwargs.get("paid", "all"), kwargs.get("time"), kwargs.get("id"), kwargs.get("limit",25)]
    return fetch_one(db,"SELECT get_rider_jobs(%s,%s,%s,%s,%s,%s,%s,%s,%s)",args)


def dispatch(db, rid=RIDER, status="completed", amount=3.25, paid="unpaid", when="2026-10-25 12:00:00"):
    return fetch_one(db,"INSERT INTO delivery_dispatch(order_number,rider_id,status,rider_payout,paid_status,dtts) VALUES('RDASH-JOB',%s,%s,%s,%s,%s) RETURNING dispatch_id", (rid,status,amount,paid,when))


def test_actor_authorization_and_single_use_even_inactive(db):
    assert mint(db,1234) == {"result":"not_linked"}
    session(db)
    assert activate(db)["result"] == "invalid"
    assert fetch_one(db,"SELECT rider_dashboard_session(%s,%s)",(COOKIE,UA))["rider_id"] == RIDER
    assert fetch_one(db,"SELECT rider_dashboard_session(%s,%s)",(COOKIE,"d"*64)) == {"result":"invalid"}


def test_expiry_and_wrong_role(db):
    mint(db)
    db.execute("UPDATE auth_sessions SET expires_at=now()-interval '1 second' WHERE token_hash=%s",(TOKEN,))
    assert activate(db)["result"] == "invalid"
    db.execute("UPDATE auth_sessions SET role='sys_admin',expires_at=now()+interval '1 hour' WHERE token_hash=%s",(TOKEN,))
    assert activate(db)["result"] == "invalid"


@pytest.mark.parametrize("change", ["revoked=true", "hard_expires_at=now()-interval '1 second'", "last_seen_at=now()-interval '61 minutes'", "hard_expires_at=NULL", "activated_at=NULL", "bound_ua_hash=NULL"])
def test_invalid_and_incomplete_sessions_never_read(db, change):
    session(db)
    db.execute("UPDATE auth_sessions SET "+change+" WHERE cookie_hash=%s",(COOKIE,))
    assert jobs(db)["result"] == "invalid"


def test_heartbeat_executes_and_keeps_absolute_cap(db):
    session(db)
    db.execute("UPDATE auth_sessions SET last_seen_at=now()-interval '50 minutes' WHERE cookie_hash=%s",(COOKIE,))
    before = db.execute("SELECT last_seen_at,hard_expires_at FROM auth_sessions WHERE cookie_hash=%s",(COOKIE,)).fetchone()
    assert fetch_one(db,"SELECT rider_dashboard_touch(%s,%s)",(COOKIE,UA))["result"] == "ok"
    after = db.execute("SELECT last_seen_at,hard_expires_at FROM auth_sessions WHERE cookie_hash=%s",(COOKIE,)).fetchone()
    assert after[0] > before[0] and after[1] == before[1]


def test_relink_revokes_pending_and_active_credentials(db):
    session(db)
    assert mint(db,token="d"*64)["result"] == "ok"
    assert fetch_one(db,"SELECT t_rider_link(899,899,%s,'new','New')",(RIDER,))["result"] == "relinked"
    assert jobs(db)["result"] == "invalid"
    assert activate(db,token="d"*64)["result"] == "invalid"
    assert mint(db)["result"] == "not_linked"
    assert mint(db,actor=899,token="e"*64)["result"] == "ok"


def test_concurrent_activation_has_one_winner(db):
    mint(db)
    def attempt(cookie):
        with psycopg.connect(URI,autocommit=True) as conn:
            return activate(conn,cookie=cookie)["result"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt,["1"*64,"2"*64])) == ["invalid","ok"]


def test_earnings_exclude_offers_other_riders_and_current(db):
    session(db)
    for status in ("unassigned","accepted","declined","missed","timedout","assigned","pickedup"):
        dispatch(db,status=status,amount=99)
    dispatch(db,amount=4.995,paid="paid")
    dispatch(db,amount=3.25)
    dispatch(db,rid=OTHER,amount=500)
    out=jobs(db)
    assert out["summary"] == {"count":2,"earned_minor":825,"paid_minor":500,"unpaid_minor":325}
    assert len(out["rows"]) == 2 and all(r["status"]=="completed" for r in out["rows"])
    assert out["rows"][0]["restaurant_name"] is None  # missing enrichment never removes earnings
    assert jobs(db,"current")["summary"] == {"count":2,"expected_minor":19800}
    assert jobs(db,paid="paid")["summary"]["count"] == 1


def test_totals_are_not_truncated_and_cursor_does_not_change_them(db):
    session(db)
    db.execute("SET TIME ZONE 'Europe/Berlin'")  # output contract is UTC regardless of the caller's timezone
    db.execute("INSERT INTO delivery_dispatch(order_number,rider_id,status,rider_payout,dtts) SELECT 'RDASH-BULK',%s,'completed',1.25,'2026-10-25 12:00'::timestamp FROM generate_series(1,1005)",(RIDER,))
    first=jobs(db,limit=50)
    assert first['nextCursor']['time'].endswith('+00:00')
    assert len(first["rows"])==50 and first["summary"]["earned_minor"]==125625
    second=jobs(db,limit=50,time=first["nextCursor"]["time"],id=first["nextCursor"]["id"])
    assert first["summary"]==second["summary"]
    assert not {r["dispatch_id"] for r in first["rows"]} & {r["dispatch_id"] for r in second["rows"]}


@pytest.mark.parametrize("day,inside,outside",[("2026-03-29","2026-03-29 22:59:59","2026-03-29 23:00:00"),("2026-10-25","2026-10-24 23:00:00","2026-10-24 22:59:59")])
def test_london_day_bounds_cover_dst(db,day,inside,outside):
    session(db); dispatch(db,when=inside); dispatch(db,when=outside)
    assert jobs(db,start=day,end=day)["summary"]["count"]==1


def test_profile_is_masked_before_serialization(db):
    session(db)
    db.execute("INSERT INTO rider_registrations(phone,bank_account,sort_code) VALUES(%s,'12345678','112233')",("+"+RIDER,))
    out=fetch_one(db,"SELECT get_rider_profile(%s,%s)",(COOKIE,UA))
    assert out["bank_account_suffix"]=="•••• 5678"
    assert '12345678' not in json.dumps(out) and '112233' not in json.dumps(out)


def test_service_role_only_and_untrusted_session_id_is_insufficient(db):
    session(db)
    assert jobs(db,"no_such_tab")["result"] == "bad_input"
    for role in ('anon','authenticated'):
        assert not fetch_one(db,"SELECT has_table_privilege(%s,'auth_sessions','SELECT')",(role,))
        assert not fetch_one(db,"SELECT has_function_privilege(%s,'get_rider_jobs(text,text,text,date,date,text,timestamptz,integer,integer)','EXECUTE')",(role,))
        assert not fetch_one(db,"SELECT has_function_privilege(%s,'rider_dashboard_mint(bigint,text)','EXECUTE')",(role,))
    with db.transaction():
        db.execute("SET LOCAL ROLE service_role")
        assert jobs(db)["result"] == "ok"


def test_source_grants_close_actual_anonymous_table_and_owner_view_reads(db):
    """Apply the exact owner-file access statements, after granting access as in the observed live baseline."""
    from scripts.datamodels.rider_dashboard_cutover import build

    session(db)
    mint(db,token='d'*64)
    db.execute(sql_path('delivery_detail.sql').read_text())
    tables={'rider_master.sql':'rider_master','rider_registrations.sql':'rider_registrations',
            'delivery_dispatch.sql':'delivery_dispatch','delivery_summary.sql':'delivery_summary',
            'delivery_detail.sql':'delivery_detail','delivery_inflight.sql':'delivery_inflight',
            'food_order_additions.sql':'food_order'}
    for table in tables.values():
        db.execute(f'GRANT ALL ON public.{table} TO anon,authenticated')
    db.execute('GRANT ALL ON public.ordelo_config,public.restaurant_master TO anon,authenticated')
    # Only privileges are exercised here; checkpoint column/serialization semantics remain library-owned.
    history=('thread','checkpoints','checkpoint_blobs','checkpoint_writes')
    for table in history:
        if table!='thread': db.execute('CREATE TABLE IF NOT EXISTS public.'+table+' (record text)')
        db.execute('GRANT ALL ON public.'+table+' TO anon,authenticated')
    views=('v_admin_orders','v_admin_order_items','v_admin_orders_daily','v_admin_orders_monthly')
    for view in views:
        db.execute(f'CREATE VIEW public.{view} AS SELECT * FROM delivery_dispatch')
        db.execute(f'GRANT SELECT ON public.{view} TO anon,authenticated')
    db.execute(sql_path('get_rider_payout_report.sql').read_text())
    db.execute(build())  # the actual generated owner cutover, not a hand-written test approximation
    assert jobs(db)['result']=='invalid'
    assert activate(db,token='d'*64)['result']=='invalid'
    assert mint(db,token='e'*64)['result']=='ok'
    for role in ('anon','authenticated'):
        for authority in ('ordelo_config','restaurant_master'):
            assert not fetch_one(db,'SELECT has_table_privilege(%s,%s,\'UPDATE\')',(role,authority))
        for table in [*tables.values(),*views,*history]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with db.transaction():
                    db.execute('SET LOCAL ROLE '+role)
                    db.execute('SELECT * FROM public.'+table+' LIMIT 1')
    for view in views: db.execute('DROP VIEW public.'+view)


def test_invalid_financial_data_is_not_zero_earnings(db):
    session(db); dispatch(db,amount=float('nan'))
    assert jobs(db)['result']=='bad_data'
