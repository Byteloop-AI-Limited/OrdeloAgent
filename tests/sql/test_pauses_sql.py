"""Pauses (ordelo_datamodels/availability/pauses.sql + job_pause_sweep.sql) on the isolated DB (ADR 0013, D51).

Proves the design's main claim: availability is computed from the clock, so an expired pause stops counting at once,
before and without any sweep; the sweep only closes rows and asks the app to send messages, marking them on 2xx.
Also: durations come only from ordelo_config, a second /off moves the end (never stacks), concurrent starts give one row,
restaurant admins go through the last-admin guard (detail in test_admin_pauses_sql.py), the /off options, and the grants. Phones are in Ofcom's drama range 07700 900xxx.
"""

from __future__ import annotations

import json
import threading

import psycopg
import pytest

from .conftest import URI, fetch_one, sql_path

pytestmark = pytest.mark.usefixtures("sql_env")

R1, R2 = "447700900601", "447700900602"
FAKE = "4477009006%"


@pytest.fixture(autouse=True)
def clean(db):
    def wipe():
        db.execute("DELETE FROM public.pauses WHERE principal LIKE %s", (FAKE,))
        db.execute("DELETE FROM public.http_calls")
        db.execute("UPDATE public.http_stub_status SET status = 200")
        db.execute("INSERT INTO public.ordelo_config (config_key, config_value) VALUES ('PAUSE_DURATIONS_RIDER', '6h,1d,3d'),"
                   " ('PAUSE_REMIND_BEFORE_MINS', '60') ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value")
    wipe()
    yield
    wipe()


def start(db, who=R1, dur="6h", audience="rider", scope=None):
    return fetch_one(db, "SELECT public.pause_start(%s, %s, %s, %s, 'telegram', '999')", (audience, who, scope, dur))


def paused(db, who=R1):
    return fetch_one(db, "SELECT public.is_paused('rider', %s, NULL)", (who,))


def backdate(db, who, ends_ago="1 minute", starts_ago="7 hours"):
    db.execute(f"UPDATE public.pauses SET starts_at = now() - interval '{starts_ago}', ends_at = now() - interval '{ends_ago}'"
               " WHERE principal = %s AND ended_at IS NULL", (who,))


def sweep(db):
    return fetch_one(db, "SELECT public.job_pause_sweep()")


def posted(db):
    return [json.loads(r[0]) for r in db.execute("SELECT body FROM public.http_calls ORDER BY id").fetchall()]


# ---- durations -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("key, hours", [("6h", 6), ("1d", 24), ("3D", 72), (" 1d ", 24)])
def test_listed_durations(db, key, hours):
    got = fetch_one(db, "SELECT extract(epoch FROM public.pause_duration('rider', %s)) / 3600", (key,))
    assert float(got) == hours


@pytest.mark.parametrize("key", ["7h", "2d", "forever", "", None, "0h", "-1d"])
def test_unlisted_durations_are_refused(db, key):
    assert start(db, dur=key) == {"result": "bad_duration"}
    assert paused(db) is False


def test_blank_config_disables_off(db):
    db.execute("UPDATE public.ordelo_config SET config_value = '' WHERE config_key = 'PAUSE_DURATIONS_RIDER'")
    assert start(db)["result"] == "bad_duration"


# ---- start / extend / end ------------------------------------------------------------------------------------------
def test_start_then_paused_then_resume(db):
    out = start(db)
    assert out["result"] == "paused" and out["pause_id"]
    assert paused(db) is True
    cur = fetch_one(db, "SELECT public.pause_current('rider', %s, NULL)", (R1,))
    assert cur["result"] == "paused" and cur["pause_id"] == out["pause_id"]
    assert fetch_one(db, "SELECT public.pause_end('rider', %s, NULL, 'resumed')", (R1,)) == {"result": "resumed", "pause_id": out["pause_id"]}
    assert paused(db) is False
    row = db.execute("SELECT end_reason, announced_at IS NOT NULL FROM public.pauses WHERE pause_id = %s", (out["pause_id"],)).fetchone()
    assert row == ("resumed", True)  # the bot replies itself: no "back on" message from the sweep
    assert fetch_one(db, "SELECT public.pause_end('rider', %s, NULL, 'resumed')", (R1,)) == {"result": "not_paused"}


def test_second_off_moves_the_end_and_never_stacks(db):
    first = start(db, dur="1d")
    db.execute("UPDATE public.pauses SET reminded_at = now() WHERE pause_id = %s", (first["pause_id"],))
    second = start(db, dur="6h")
    assert second["result"] == "extended" and second["pause_id"] == first["pause_id"]
    rows = db.execute("SELECT count(*), max(ends_at) < now() + interval '7 hours', bool_and(reminded_at IS NULL)"
                      " FROM public.pauses WHERE principal = %s", (R1,)).fetchone()
    assert rows == (1, True, True)  # one row, end replaced (6h, not 1d + 6h), reminder re-armed


def test_operator_end_reason(db):
    start(db)
    fetch_one(db, "SELECT public.pause_end('rider', %s, NULL, 'operator')", (R1,))
    assert fetch_one(db, "SELECT end_reason FROM public.pauses WHERE principal = %s", (R1,)) == "operator"


def test_rest_admin_and_unknown_audiences(db):
    """A phone that is not one of the restaurant's admins cannot pause (R6; the full guard: test_admin_pauses_sql.py)."""
    assert start(db, audience="rest_admin", scope="ELAS") == {"result": "not_admin"}
    assert start(db, audience="customer") == {"result": "bad_audience"}


def test_pause_options_follow_config_order_without_duplicates_or_junk(db):
    db.execute("UPDATE public.ordelo_config SET config_value = ' 1D, 6h,junk,1d,0h,3d' WHERE config_key = 'PAUSE_DURATIONS_RIDER'")
    assert fetch_one(db, "SELECT public.pause_options('rider')") == ["1d", "6h", "3d"]
    db.execute("UPDATE public.ordelo_config SET config_value = '' WHERE config_key = 'PAUSE_DURATIONS_RIDER'")
    assert fetch_one(db, "SELECT public.pause_options('rider')") == []
    assert fetch_one(db, "SELECT public.pause_options('nobody')") == []


def test_concurrent_offs_give_one_open_row():
    results, barrier = [], threading.Barrier(2)

    def go():
        with psycopg.connect(URI, autocommit=True) as c:
            barrier.wait()
            results.append(c.execute("SELECT public.pause_start('rider', %s, NULL, '6h', 'telegram', NULL)", (R2,)).fetchone()[0])

    threads = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(r["result"] for r in results) == ["extended", "paused"]
    with psycopg.connect(URI, autocommit=True) as c:
        assert c.execute("SELECT count(*) FROM public.pauses WHERE principal = %s AND ended_at IS NULL", (R2,)).fetchone()[0] == 1


def test_principal_must_be_digits(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        start(db, who="RIDER01")


# ---- the clock decides, not the sweep ------------------------------------------------------------------------------
def test_expired_pause_stops_counting_before_any_sweep(db):
    start(db)
    backdate(db, R1)
    assert paused(db) is False
    assert fetch_one(db, "SELECT public.pause_current('rider', %s, NULL)", (R1,)) == {"result": "not_paused"}


def test_new_off_after_an_unswept_expiry_closes_it_quietly(db):
    old = start(db)
    backdate(db, R1)
    new = start(db)
    assert new["result"] == "paused" and new["pause_id"] != old["pause_id"]
    row = db.execute("SELECT end_reason, announced_at IS NOT NULL FROM public.pauses WHERE pause_id = %s", (old["pause_id"],)).fetchone()
    assert row == ("expired", True)  # one message for the person, not "back on" right after a new /off


# ---- the sweep: close, remind, announce, mark on 2xx ---------------------------------------------------------------
def test_sweep_with_nothing_to_do_makes_no_http_call(db):
    assert sweep(db) is True
    assert posted(db) == []


def test_sweep_closes_reminds_and_announces(db):
    soon = start(db, who=R1)
    db.execute("UPDATE public.pauses SET ends_at = now() + interval '30 minutes' WHERE pause_id = %s", (soon["pause_id"],))
    gone = start(db, who=R2)
    backdate(db, R2)
    assert sweep(db) is True
    body = posted(db)[-1]
    assert body["event_type"] == "pause_sweep"
    assert [i["pause_id"] for i in body["ending_soon"]] == [soon["pause_id"]]
    assert [i["pause_id"] for i in body["ended"]] == [gone["pause_id"]]
    assert body["ended"][0]["audience"] == "rider" and body["ended"][0]["principal"] == R2
    marks = dict(db.execute("SELECT pause_id, (reminded_at IS NOT NULL, announced_at IS NOT NULL, end_reason)::text"
                            " FROM public.pauses WHERE principal LIKE %s", (FAKE,)).fetchall())
    assert marks[soon["pause_id"]] == "(t,f,)"
    assert marks[gone["pause_id"]] == "(f,t,expired)"
    # Nothing new on the next run.
    db.execute("DELETE FROM public.http_calls")
    sweep(db)
    assert posted(db) == []


def test_failed_post_marks_nothing_and_retries(db):
    gone = start(db, who=R2)
    backdate(db, R2)
    db.execute("UPDATE public.http_stub_status SET status = 503")
    assert sweep(db) is False
    row = db.execute("SELECT end_reason, announced_at FROM public.pauses WHERE pause_id = %s", (gone["pause_id"],)).fetchone()
    assert row == ("expired", None)  # closed (bookkeeping) but the message is still owed
    assert paused(db, R2) is False  # availability never depended on the POST
    db.execute("UPDATE public.http_stub_status SET status = 200")
    assert sweep(db) is True
    assert [i["pause_id"] for i in posted(db)[-1]["ended"]] == [gone["pause_id"]]


def test_old_expiries_are_not_announced(db):
    start(db, who=R2)
    backdate(db, R2, ends_ago="3 days", starts_ago="4 days")
    sweep(db)
    assert posted(db) == []


# ---- grants and repeatability --------------------------------------------------------------------------------------
@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_public_roles_cannot_call_or_read(db, role):
    db.execute(f"SET ROLE {role}")
    try:
        for sql in ("SELECT public.pause_start('rider', '447700900601', NULL, '6h', 'telegram', NULL)",
                    "SELECT public.pause_end('rider', '447700900601', NULL, 'resumed')",
                    "SELECT public.pause_current('rider', '447700900601', NULL)",
                    "SELECT public.is_paused('rider', '447700900601', NULL)",
                    "SELECT public.pause_options('rider')",
                    "SELECT public.job_pause_sweep()",
                    "SELECT * FROM public.pauses"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db.execute(sql)
    finally:
        db.execute("RESET ROLE")


def test_rls_enabled(db):
    assert fetch_one(db, "SELECT relrowsecurity FROM pg_class WHERE oid = 'public.pauses'::regclass") is True


def test_files_are_repeatable_and_schedule_the_job(db):
    db.execute(sql_path("pauses.sql").read_text())
    db.execute(sql_path("job_pause_sweep.sql").read_text())
    assert fetch_one(db, "SELECT schedule FROM cron.job WHERE jobname = 'job_pause_sweep'") == "* * * * *"
