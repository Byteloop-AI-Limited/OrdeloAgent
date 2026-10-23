"""Rider threads, one per assigned dispatch (ordelo_datamodels/agent_threads/rider_threads.sql), on the isolated DB.

Covers every result value of rider_thread_open / touch / active / describe / close, the single-open-thread rule (D47) with
its cancel-reason note on declined dispatches, legacy 'ORDELO-<uuid>' threads, threads of other agents left alone, the
channel stamped on delivery_dispatch from rider_master (D44, trigger in dispatch/delivery_dispatch.sql), two assignments of
one rider at the same moment, and the server-only grants. Phones are in Ofcom's drama range 07700 900xxx.
"""

from __future__ import annotations

import threading
import time

import psycopg
import pytest

from .conftest import URI, fetch_one

pytestmark = pytest.mark.usefixtures("sql_env")

AGENT = "ORDELO"
R1, R2 = "447700900601", "447700900602"
FAKE = "4477009006%"


def _wipe(db):
    db.execute("DELETE FROM public.thread WHERE recipient LIKE %s", (FAKE,))
    db.execute("DELETE FROM public.delivery_dispatch WHERE rider_id LIKE %s", (FAKE,))
    db.execute("DELETE FROM public.rider_master WHERE rider_id LIKE %s", (FAKE,))


@pytest.fixture(autouse=True)
def clean(db):
    _wipe(db)
    db.execute(
        "INSERT INTO public.rider_master (rider_id, rider_name, vehicle_type, town, status, channel, tuid, tcid)"
        " VALUES (%s, 'Sam', 'bike', 'Salisbury', 'active', 'telegram', 999000000601, 999000000601),"
        "        (%s, 'Ana', 'car', 'Salisbury', 'active', 'whatsapp', NULL, NULL)",
        (R1, R2),
    )
    yield
    _wipe(db)


def dispatch(db, rider=R1, order="STRK-TEST-T1", status="assigned", channel=None) -> int:
    cols, vals = "order_number, rider_id, status", [order, rider, status]
    if channel:  # the trigger stamps rider_master.channel whatever is given
        cols, vals = cols + ", channel", vals + [channel]
    return fetch_one(db, f"INSERT INTO public.delivery_dispatch ({cols}) VALUES (%s, %s, %s{', %s' if channel else ''})"
                         " RETURNING dispatch_id", vals)


def call(db, fn, *args):
    return fetch_one(db, f"SELECT public.{fn}({', '.join(['%s'] * len(args))})", args)


def thread_row(db, thread_id):
    return db.execute("SELECT agent, recipient, is_active FROM public.thread WHERE thread_id = %s", (thread_id,)).fetchone()


# ---- the dispatch's channel (D44) ----------------------------------------------------------------------------------
def test_dispatch_channel_is_stamped_from_the_rider_at_insert(db):
    d1 = dispatch(db, R1, channel="whatsapp")  # a value given by the caller is overwritten
    d2 = dispatch(db, R2)
    d3 = dispatch(db, "447700900699")  # unknown rider -> whatsapp
    got = dict(db.execute("SELECT dispatch_id, channel FROM public.delivery_dispatch WHERE dispatch_id = ANY(%s)",
                          ([d1, d2, d3],)).fetchall())
    assert got == {d1: "telegram", d2: "whatsapp", d3: "whatsapp"}
    db.execute("UPDATE public.rider_master SET channel = 'whatsapp' WHERE rider_id = %s", (R1,))
    assert fetch_one(db, "SELECT channel FROM public.delivery_dispatch WHERE dispatch_id = %s", (d1,)) == "telegram"


def test_thread_id_is_agent_dispatch_id():
    with psycopg.connect(URI, autocommit=True) as c:
        assert c.execute("SELECT public.rider_thread_id('ORDELO', 84217)").fetchone()[0] == "ORDELO-dispatch-84217"


# ---- rider_thread_open ---------------------------------------------------------------------------------------------
def test_open_creates_the_thread_and_records_it_on_the_dispatch(db):
    d = dispatch(db)
    out = call(db, "rider_thread_open", AGENT, R1, d)
    tid = f"ORDELO-dispatch-{d}"
    assert out == {"result": "opened", "thread_id": tid, "closed": []}
    assert thread_row(db, tid) == (AGENT, R1, True)
    assert fetch_one(db, "SELECT thread_id FROM public.delivery_dispatch WHERE dispatch_id = %s", (d,)) == tid


def test_open_again_is_existing_and_a_closed_thread_is_never_reopened(db):
    d = dispatch(db)
    call(db, "rider_thread_open", AGENT, R1, d)
    assert call(db, "rider_thread_open", AGENT, R1, d)["result"] == "existing"
    call(db, "rider_thread_close", f"ORDELO-dispatch-{d}")
    assert call(db, "rider_thread_open", AGENT, R1, d)["result"] == "closed"
    assert thread_row(db, f"ORDELO-dispatch-{d}")[2] is False


def test_open_refuses_a_missing_or_foreign_dispatch(db):
    d = dispatch(db, R2)
    assert call(db, "rider_thread_open", AGENT, R1, d)["result"] == "not_found"
    assert call(db, "rider_thread_open", AGENT, R1, 987654321)["result"] == "not_found"
    assert db.execute("SELECT count(*) FROM public.thread WHERE recipient = %s", (R1,)).fetchone()[0] == 0


def test_open_closes_the_riders_other_threads_and_notes_a_missing_decline_reason(db):
    d_old = dispatch(db, order="STRK-TEST-T1")
    call(db, "rider_thread_open", AGENT, R1, d_old)
    d_kept = dispatch(db, order="STRK-TEST-T2")
    call(db, "rider_thread_open", AGENT, R1, d_kept)  # closes d_old's thread (D47)
    # d_old was declined with no reason; d_kept declined with a reason, then a third job starts
    db.execute("UPDATE public.delivery_dispatch SET status = 'declined' WHERE dispatch_id = ANY(%s)", ([d_old, d_kept],))
    db.execute("UPDATE public.delivery_dispatch SET reason_for_decline = 'flat tyre' WHERE dispatch_id = %s", (d_kept,))
    legacy = "ORDELO-0f1e2d3c-legacy"
    other_agent = "ELAS-customer-thread"
    db.execute("INSERT INTO public.thread (thread_id, agent, recipient, is_active) VALUES (%s, 'ORDELO', %s, TRUE),"
               " (%s, 'ELAS', %s, TRUE)", (legacy, R1, other_agent, R1))
    d_new = dispatch(db, order="STRK-TEST-T3")
    out = call(db, "rider_thread_open", AGENT, R1, d_new)
    assert out["result"] == "opened"
    assert sorted(out["closed"]) == sorted([f"ORDELO-dispatch-{d_kept}", legacy])
    active = [r[0] for r in db.execute("SELECT thread_id FROM public.thread WHERE recipient = %s AND is_active", (R1,))]
    assert sorted(active) == sorted([f"ORDELO-dispatch-{d_new}", other_agent])  # a customer/other-agent thread is untouched
    reasons = dict(db.execute("SELECT dispatch_id, reason_for_decline FROM public.delivery_dispatch WHERE dispatch_id = ANY(%s)",
                              ([d_old, d_kept, d_new],)).fetchall())
    # d_old's thread was closed by the earlier open, while it was still 'assigned': nothing to note. d_kept keeps its own.
    assert reasons == {d_old: None, d_kept: "flat tyre", d_new: None}


def test_open_notes_the_reason_on_a_declined_dispatch_whose_thread_it_closes(db):
    d_old = dispatch(db, order="STRK-TEST-T1")
    call(db, "rider_thread_open", AGENT, R1, d_old)
    db.execute("UPDATE public.delivery_dispatch SET status = 'declined' WHERE dispatch_id = %s", (d_old,))
    d_new = dispatch(db, order="STRK-TEST-T2")
    call(db, "rider_thread_open", AGENT, R1, d_new)
    assert fetch_one(db, "SELECT reason_for_decline FROM public.delivery_dispatch WHERE dispatch_id = %s", (d_old,)) == (
        "not given (next job started)")


def test_two_assignments_of_one_rider_at_once_leave_one_open_thread(db):
    d1, d2 = dispatch(db, order="STRK-TEST-T1"), dispatch(db, order="STRK-TEST-T2")
    first = psycopg.connect(URI)  # a transaction holding the per-rider lock
    try:
        first.execute("SELECT public.rider_thread_open(%s, %s, %s)", (AGENT, R1, d1))
        second_result = []

        def second():
            with psycopg.connect(URI, autocommit=True) as c:
                second_result.append(c.execute("SELECT public.rider_thread_open(%s, %s, %s)", (AGENT, R1, d2)).fetchone()[0])

        t = threading.Thread(target=second)
        t.start()
        time.sleep(0.3)
        assert second_result == []  # blocked on pg_advisory_xact_lock until the first commits
        first.commit()
        t.join(5)
    finally:
        first.close()
    assert second_result[0]["result"] == "opened" and second_result[0]["closed"] == [f"ORDELO-dispatch-{d1}"]
    active = [r[0] for r in db.execute("SELECT thread_id FROM public.thread WHERE recipient = %s AND is_active", (R1,))]
    assert active == [f"ORDELO-dispatch-{d2}"]


# ---- touch / active / describe / close -----------------------------------------------------------------------------
def test_touch_refreshes_only_an_open_thread(db):
    d = dispatch(db)
    tid = call(db, "rider_thread_open", AGENT, R1, d)["thread_id"]
    db.execute("UPDATE public.thread SET last_access_dtts = now() - interval '2 hours' WHERE thread_id = %s", (tid,))
    snap = call(db, "rider_thread_touch", tid)
    assert snap == {"result": "active", "thread_id": tid, "rider_id": R1, "is_active": True, "dispatch_id": d,
                    "order_number": "STRK-TEST-T1", "dispatch_status": "assigned", "channel": "telegram",
                    "tcid": 999000000601}
    assert fetch_one(db, "SELECT last_access_dtts > now() - interval '1 minute' FROM public.thread WHERE thread_id = %s", (tid,))
    call(db, "rider_thread_close", tid)
    db.execute("UPDATE public.thread SET last_access_dtts = now() - interval '2 hours' WHERE thread_id = %s", (tid,))
    assert call(db, "rider_thread_touch", tid)["result"] == "inactive"
    assert fetch_one(db, "SELECT last_access_dtts < now() - interval '1 hour' FROM public.thread WHERE thread_id = %s", (tid,))
    assert call(db, "rider_thread_touch", "ORDELO-dispatch-0") == {"result": "not_found"}


def test_active_finds_the_open_thread_with_or_without_touching(db):
    assert call(db, "rider_thread_active", AGENT, R2, True) == {"result": "none"}
    d = dispatch(db, R2)
    tid = call(db, "rider_thread_open", AGENT, R2, d)["thread_id"]
    db.execute("UPDATE public.thread SET last_access_dtts = now() - interval '2 hours' WHERE thread_id = %s", (tid,))
    snap = call(db, "rider_thread_active", AGENT, R2, False)
    assert (snap["result"], snap["thread_id"], snap["channel"], snap["tcid"]) == ("active", tid, "whatsapp", None)
    assert fetch_one(db, "SELECT last_access_dtts < now() - interval '1 hour' FROM public.thread WHERE thread_id = %s", (tid,))
    call(db, "rider_thread_active", AGENT, R2, True)
    assert fetch_one(db, "SELECT last_access_dtts > now() - interval '1 minute' FROM public.thread WHERE thread_id = %s", (tid,))


def test_active_still_finds_a_legacy_thread_opened_before_r2(db):
    db.execute("INSERT INTO public.thread (thread_id, agent, recipient, is_active) VALUES ('ORDELO-legacy-1', 'ORDELO', %s, TRUE)",
               (R1,))
    snap = call(db, "rider_thread_active", AGENT, R1, False)
    assert snap["result"] == "active" and snap["thread_id"] == "ORDELO-legacy-1"
    assert (snap["dispatch_id"], snap["order_number"], snap["channel"]) == (None, None, "whatsapp")


def test_describe_by_thread_or_by_dispatch(db):
    d = dispatch(db)
    tid = call(db, "rider_thread_open", AGENT, R1, d)["thread_id"]
    by_tid = call(db, "rider_thread_describe", tid, None)
    by_dispatch = call(db, "rider_thread_describe", None, d)
    assert by_tid == by_dispatch and by_tid["result"] == "found" and by_tid["dispatch_id"] == d
    assert call(db, "rider_thread_describe", None, dispatch(db, order="STRK-TEST-T9")) == {"result": "not_found"}


def test_close_closes_exactly_one_thread(db):
    d1 = dispatch(db, R1)
    t1 = call(db, "rider_thread_open", AGENT, R1, d1)["thread_id"]
    d2 = dispatch(db, R2)
    t2 = call(db, "rider_thread_open", AGENT, R2, d2)["thread_id"]
    assert call(db, "rider_thread_close", t1) == {"result": "closed", "thread_id": t1}
    assert call(db, "rider_thread_close", t1) == {"result": "not_active", "thread_id": t1}
    assert thread_row(db, t2)[2] is True


# ---- grants --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_public_roles_cannot_call(db, role):
    db.execute(f"SET ROLE {role}")
    try:
        for sql in ("SELECT public.rider_thread_id('ORDELO', 1)",
                    "SELECT public.rider_thread_open('ORDELO', '447700900601', 1)",
                    "SELECT public.rider_thread_touch('x')",
                    "SELECT public.rider_thread_active('ORDELO', '447700900601', false)",
                    "SELECT public.rider_thread_describe('x', NULL)",
                    "SELECT public.rider_thread_close('x')"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db.execute(sql)
    finally:
        db.execute("RESET ROLE")
