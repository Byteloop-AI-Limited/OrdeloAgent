"""Isolated-database tests for ordelo_datamodels/restaurant_admin/restaurant_ready_adjust_notices.sql.

Covers Ready (shared, first tap per dispatch wins), adjust pickup (relative, 'unchanged' writes nothing), the Telegram
wrappers (D14), the receipt status keys, snapshot, send/take/stale functions, the refresh job, plain notices and grants.
Skipped without ORDELO_TEST_DB_URI. Plan: plans/telegram-phase-7-8-kitchen-actions-and-notices.md section 6.1.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from .conftest import _connect, fetch_one

pytestmark = pytest.mark.usefixtures("sql_env")

BOT = "rest_admin"
ORDER = "ELAS-CEKT-22"
TAKE = "ELAS-TAKE-7"
ADA, BOB, CAT = "447700900001", "447700900002", "447700900003"  # CAT is a person who is not in restaurant_master.admins


@pytest.fixture(autouse=True)
def clean(db):
    db.execute(
        "TRUNCATE public.delivery_summary, public.takeaway_summary, public.t_invites, public.restaurant_master, "
        "public.t_order_alerts, public.t_sent_messages, public.t_inbox, public.food_order, public.order_item, "
        "public.http_calls, public.trigger_log, public.delivery_inflight, public.delivery_dispatch, public.rider_master "
        "RESTART IDENTITY CASCADE"
    )
    db.execute("UPDATE public.http_stub_status SET status = 200")
    db.execute("INSERT INTO public.restaurant_master (rest_ref, rest_name, admins) VALUES ('ELAS', 'Elas Kitchen', %s)", ([ADA, BOB],))


# ---- helpers ---------------------------------------------------------------------------------------------------


def link(db, phone=ADA, uid=111, first="Ada", status="claimed", rest="ELAS"):
    db.execute(
        "INSERT INTO public.t_invites (rest_ref, phone_number, status, claimed_at, telegram_user_id, telegram_chat_id, telegram_first_name) "
        "VALUES (%s, %s, %s, now(), %s, %s, %s)", (rest, phone, status, uid, uid, first))


def delivery(db, number=ORDER, pickup="now() + interval '30 minutes'", **cols):
    """An accepted delivery order with a pickup time (status 'assigned' once a rider is attached with rider())."""
    db.execute(
        f"INSERT INTO public.delivery_summary (order_number, status, restaurant_confirmation_status, restaurant_admin, pickup_time, customer_id) "
        f"VALUES (%s, 'unassigned', 'restaurant_accept', %s, {pickup}, '447700900099')", (number, ADA))
    for k, v in cols.items():
        db.execute(f"UPDATE public.delivery_summary SET {k} = %s WHERE order_number = %s", (v, number))
    db.execute("INSERT INTO public.food_order (order_id, order_number, total_price, notes, small_order_fee, payment_status) "
               "VALUES (%s, %s, 23.5, 'No <onions> & extra naan', 1.5, 'paid') ON CONFLICT DO NOTHING", (number, number))
    db.execute("INSERT INTO public.order_item (order_id, product_name, quantity, price, modifications) VALUES "
               "(%s, 'Naan', 1, 3.0, NULL), (%s, 'Biryani', 2, 8.5, %s)", (number, number, ["Extra spicy", "No nuts"]))
    db.execute("TRUNCATE public.trigger_log")
    return number


def rider(db, number=ORDER, rid="RID1", name="Raj", dispatch_status="assigned"):
    """A rider on the job: dispatch row + inflight row (what job_assign_dispatch leaves), summary status 'assigned'."""
    db.execute("INSERT INTO public.rider_master (rider_id, rider_name) SELECT %s, %s WHERE NOT EXISTS "
               "(SELECT 1 FROM public.rider_master WHERE rider_id = %s)", (rid, name, rid))
    did = fetch_one(db, "INSERT INTO public.delivery_dispatch (order_number, rider_id, status) VALUES (%s, %s, %s) RETURNING dispatch_id",
                    (number, rid, dispatch_status))
    db.execute("INSERT INTO public.delivery_inflight (dispatch_id, order_number, rider_id) VALUES (%s, %s, %s)", (did, number, rid))
    db.execute("UPDATE public.delivery_summary SET status = 'assigned' WHERE order_number = %s", (number,))
    return did


def cancel_rider(db, did):
    """What dispatch_cancel_before_pickup leaves: the inflight row is gone and the order is open again."""
    db.execute("DELETE FROM public.delivery_inflight WHERE dispatch_id = %s", (did,))
    db.execute("UPDATE public.delivery_dispatch SET status = 'declined' WHERE dispatch_id = %s", (did,))
    db.execute("UPDATE public.delivery_summary SET status = 'unassigned' WHERE order_number = %s", (ORDER,))


def takeaway(db, number=TAKE, status="pickup_confirmed", payment="paid"):
    db.execute("INSERT INTO public.takeaway_summary (order_number, status, restaurant_confirmation_status, restaurant_admin, pickup_time) "
               "VALUES (%s, %s, 'restaurant_accept', %s, now() + interval '20 minutes')", (number, status, ADA))
    db.execute("INSERT INTO public.food_order (order_id, order_number, total_price, payment_status) VALUES (%s, %s, 12.0, %s)",
               (number, number, payment))
    db.execute("INSERT INTO public.order_item (order_id, product_name, quantity, price) VALUES (%s, 'Dosa', 1, 12.0)", (number,))
    return number


def ready(db, number=ORDER, kind="delivery", phone=ADA):
    return fetch_one(db, "SELECT public.restaurant_order_ready(%s, %s, %s, 'test')", (number, kind, phone))


def adjust(db, target_sql, number=ORDER, phone=ADA):
    return fetch_one(db, f"SELECT public.restaurant_order_adjust_pickup(%s, {target_sql}, %s, 'test')", (number, phone))


def row(db, sql, params=None):
    return db.execute(sql, params or ()).fetchone()


def triggers(db):
    return db.execute("SELECT tbl, order_number, reason FROM public.trigger_log ORDER BY id").fetchall()


def pickup(db, number=ORDER):
    return fetch_one(db, "SELECT pickup_time FROM public.delivery_summary WHERE order_number = %s", (number,))


# ---- Ready: delivery -------------------------------------------------------------------------------------------


def test_ready_delivery_ok_records_who_and_dispatch(db):
    delivery(db)
    did = rider(db)
    out = ready(db)
    assert out["result"] == "ok"
    assert out["rider_id"] == "RID1" and out["dispatch_id"] == did and out["rest_name"] == "Test Kitchen"
    assert out["ready_by_phone"] == ADA
    r = row(db, "SELECT ready_by, ready_dispatch_id, ready_at IS NOT NULL FROM public.delivery_summary WHERE order_number = %s", (ORDER,))
    assert r == (ADA, did, True)


def test_ready_twice_same_dispatch_is_already_ready_with_label(db):
    delivery(db)
    rider(db)
    link(db)  # claimed invite: first name "Ada"
    ready(db)
    out = ready(db, phone=BOB)
    assert out["result"] == "already_ready"
    assert out["ready_by"] == "Ada" and out["ready_by_phone"] == ADA


def test_ready_label_falls_back_to_last_four_digits_without_invite(db):
    delivery(db)
    rider(db)
    ready(db)
    assert ready(db)["ready_by"] == "…0001"


def test_ready_race_two_connections_one_wins(db):
    delivery(db)
    rider(db)
    a = _connect(autocommit=False)
    try:
        first = fetch_one(a, "SELECT public.restaurant_order_ready(%s, 'delivery', %s, 'test')", (ORDER, ADA))  # holds the row lock
        results = []

        def second():
            with _connect() as b:
                results.append(fetch_one(b, "SELECT public.restaurant_order_ready(%s, 'delivery', %s, 'test')", (ORDER, BOB)))

        t = threading.Thread(target=second)
        t.start()
        time.sleep(0.4)  # the second call is now blocked on the UPDATE's row lock
        assert t.is_alive()
        a.commit()
        t.join(5)
    finally:
        a.close()
    assert first["result"] == "ok"
    assert [r["result"] for r in results] == ["already_ready"]
    assert results[0]["ready_by_phone"] == ADA


def test_ready_not_in_progress_without_inflight(db):
    delivery(db)
    assert ready(db) == {"result": "not_ready_state", "progress": "not_in_progress"}


def test_ready_after_pickup_is_picked_up(db):
    delivery(db)
    rider(db, dispatch_status="pickedup")
    assert ready(db) == {"result": "not_ready_state", "progress": "picked_up"}
    assert row(db, "SELECT ready_at FROM public.delivery_summary")[0] is None


def test_ready_unknown_order_and_bad_type(db):
    assert ready(db, "ELAS-NONE-1") == {"result": "not_found"}
    with pytest.raises(Exception, match="bad order type"):
        ready(db, kind="pizza")


def test_ready_new_dispatch_after_cancel_can_be_ready_again(db):
    delivery(db)
    did1 = rider(db)
    assert ready(db)["result"] == "ok"
    cancel_rider(db, did1)
    assert ready(db)["result"] == "not_ready_state"  # nobody on the job
    did2 = rider(db, rid="RID2", name="Sam")
    out = ready(db)
    assert out["result"] == "ok" and out["rider_id"] == "RID2" and out["dispatch_id"] == did2


def test_ready_does_not_fire_restaurant_trigger(db):
    delivery(db)
    rider(db)
    ready(db)
    assert triggers(db) == []


# ---- Ready: takeaway -------------------------------------------------------------------------------------------


def test_ready_takeaway_ok_once_then_already_ready(db):
    takeaway(db)
    out = ready(db, TAKE, "takeaway")
    assert out["result"] == "ok" and out["rest_name"] == "Test Kitchen" and out["customer_id"] == "447700900001"
    assert out["recipient"] == "447700900001" and out["order_id"] == TAKE
    again = ready(db, TAKE, "takeaway", BOB)
    assert again["result"] == "already_ready" and again["ready_by_phone"] == ADA


def test_ready_takeaway_needs_pickup_confirmed(db):
    takeaway(db, status="restaurant_unconfirmed")
    assert ready(db, TAKE, "takeaway") == {"result": "not_ready_state", "progress": "not_in_progress"}
    assert ready(db, "ELAS-NONE-1", "takeaway") == {"result": "not_found"}


# ---- adjust pickup ---------------------------------------------------------------------------------------------


def test_adjust_relative_to_initial_not_cumulative(db):
    delivery(db, pickup="date_trunc('minute', now()) + interval '30 minutes'")
    rider(db)
    base = pickup(db)
    assert adjust(db, "%s::timestamptz + interval '10 minutes'" % "(SELECT pickup_time FROM public.delivery_summary)")["result"] == "ok"
    init = row(db, "SELECT pickup_time_initial FROM public.delivery_summary")[0]
    assert init == base
    # the Telegram wrapper is relative to the initial pickup: +20 then +10 do not accumulate
    link(db)
    assert fetch_one(db, "SELECT public.t_order_adjust_pickup(%s, 111, %s, 20)", (BOT, ORDER))["result"] == "ok"
    assert pickup(db) == fetch_one(db, "SELECT %s::timestamptz + interval '20 minutes'", (base,))
    assert fetch_one(db, "SELECT public.t_order_adjust_pickup(%s, 111, %s, 10)", (BOT, ORDER))["result"] == "ok"
    assert pickup(db) == fetch_one(db, "SELECT %s::timestamptz + interval '10 minutes'", (base,))
    assert row(db, "SELECT pickup_time_initial FROM public.delivery_summary")[0] == base  # kept from the first adjust


def test_adjust_same_target_is_unchanged_and_writes_nothing(db):
    delivery(db)
    rider(db)
    cur = pickup(db)
    out = adjust(db, "(SELECT pickup_time FROM public.delivery_summary)")
    assert out["result"] == "unchanged"
    assert pickup(db) == cur
    assert triggers(db) == []
    assert row(db, "SELECT pickup_time_initial, pickup_adjusted_by, pickup_adjusted_at FROM public.delivery_summary") == (None, None, None)


def test_adjust_fires_restaurant_trigger_once(db):
    delivery(db)
    rider(db)
    adjust(db, "(SELECT pickup_time + interval '10 minutes' FROM public.delivery_summary)")
    assert triggers(db) == [("delivery_summary", ORDER, "restaurant_pickuptime_adjusted")]


def test_adjust_keeps_restaurant_admin_and_records_adjuster(db):
    delivery(db)
    rider(db)
    out = adjust(db, "(SELECT pickup_time + interval '20 minutes' FROM public.delivery_summary)", phone=BOB)
    assert out["by_phone"] == BOB
    r = row(db, "SELECT restaurant_admin, pickup_adjusted_by, pickup_adjusted_at IS NOT NULL, restaurant_confirmation_status "
                "FROM public.delivery_summary")
    assert r == (ADA, BOB, True, "restaurant_pickuptime_adjusted")


def test_adjust_gate_states(db):
    delivery(db)
    target = "now() + interval '1 hour'"
    assert adjust(db, target) == {"result": "not_ready_state", "progress": "not_in_progress"}
    did = rider(db, dispatch_status="pickedup")
    assert adjust(db, target) == {"result": "not_ready_state", "progress": "picked_up"}
    assert adjust(db, target, number="ELAS-NONE-1") == {"result": "not_found"}
    assert did
    with pytest.raises(Exception, match="missing target"):
        adjust(db, "NULL::timestamptz")


def test_adjust_card_status_stays_pickup_set(db):
    delivery(db)
    rider(db)
    adjust(db, "(SELECT pickup_time + interval '10 minutes' FROM public.delivery_summary)")
    rcs, pk = row(db, "SELECT restaurant_confirmation_status, pickup_time FROM public.delivery_summary")
    assert fetch_one(db, "SELECT public.t_order_card_status(%s, %s)", (rcs, pk)) == "pickup_set"


# ---- Telegram wrappers (D14) -----------------------------------------------------------------------------------


def test_t_order_ready_authorised_and_label(db):
    delivery(db)
    rider(db)
    link(db)
    out = fetch_one(db, "SELECT public.t_order_ready(%s, 111, %s, 'delivery')", (BOT, ORDER))
    assert out["result"] == "ok" and out["ready_by"] == "Ada" and out["ready_by_phone"] == ADA


@pytest.mark.parametrize("case", ["revoked", "unlisted", "unknown_user", "other_restaurant"])
def test_t_order_ready_and_adjust_not_authorised(db, case):
    delivery(db)
    rider(db)
    if case == "revoked":
        link(db, status="revoked")
    elif case == "unlisted":
        link(db, phone=CAT, uid=222, first="Cat")
    elif case == "other_restaurant":
        db.execute("INSERT INTO public.restaurant_master (rest_ref, rest_name, admins) VALUES ('ZZZZ', 'Other', %s)", ([ADA],))
        link(db, rest="ZZZZ")
    uid = 999 if case == "unknown_user" else 222 if case == "unlisted" else 111
    assert fetch_one(db, "SELECT public.t_order_ready(%s, %s, %s, 'delivery')", (BOT, uid, ORDER)) == {"result": "not_authorised"}
    assert fetch_one(db, "SELECT public.t_order_adjust_pickup(%s, %s, %s, 10)", (BOT, uid, ORDER)) == {"result": "not_authorised"}
    assert row(db, "SELECT ready_at FROM public.delivery_summary")[0] is None


def test_t_order_wrappers_not_found(db):
    link(db)
    assert fetch_one(db, "SELECT public.t_order_ready(%s, 111, 'ELAS-NONE-1', 'delivery')", (BOT,)) == {"result": "not_found"}
    assert fetch_one(db, "SELECT public.t_order_adjust_pickup(%s, 111, 'ELAS-NONE-1', 10)", (BOT,)) == {"result": "not_found"}


def test_t_order_adjust_rejects_other_minutes_and_ready_rejects_bad_type(db):
    delivery(db)
    rider(db)
    link(db)
    with pytest.raises(Exception, match="bad minutes"):
        fetch_one(db, "SELECT public.t_order_adjust_pickup(%s, 111, %s, 15)", (BOT, ORDER))
    with pytest.raises(Exception, match="bad order type"):
        fetch_one(db, "SELECT public.t_order_ready(%s, 111, %s, 'pizza')", (BOT, ORDER))


def test_t_order_ready_takeaway(db):
    takeaway(db)
    link(db)
    assert fetch_one(db, "SELECT public.t_order_ready(%s, 111, %s, 'takeaway')", (BOT, TAKE))["result"] == "ok"


# ---- receipt status keys (plan section 3.4) --------------------------------------------------------------------


def status(db, number=ORDER, kind="delivery", did=None):
    return fetch_one(db, "SELECT public.t_receipt_status(%s, %s, %s)", (number, kind, did))


def hm(db, number=ORDER, table="delivery_summary"):
    return fetch_one(db, f"SELECT to_char(pickup_time AT TIME ZONE 'Europe/London', 'HH24:MI') FROM public.{table} WHERE order_number = %s", (number,))


def test_receipt_status_keys_delivery(db):
    assert status(db) == "gone"
    delivery(db)
    assert status(db, did=1) == "rider_cancelled"  # no inflight row for this dispatch
    did = rider(db)
    assert status(db, did=did) == f"open@{hm(db)}"
    ready(db)
    assert status(db, did=did) == f"ready@{hm(db)}"
    adjust(db, "(SELECT pickup_time + interval '10 minutes' FROM public.delivery_summary)")
    assert status(db, did=did) == f"ready@{hm(db)}"  # key moves with the pickup time
    db.execute("UPDATE public.delivery_dispatch SET status = 'pickedup'")
    assert status(db, did=did) == "picked_up"
    db.execute("UPDATE public.delivery_dispatch SET status = 'completed'")
    db.execute("DELETE FROM public.delivery_inflight")  # dispatch_complete_func deletes the inflight row
    db.execute("UPDATE public.delivery_summary SET status = 'completed'")
    assert status(db, did=did) == "done"


def test_receipt_status_old_dispatch_after_redispatch_is_rider_cancelled(db):
    delivery(db)
    did1 = rider(db)
    cancel_rider(db, did1)
    did2 = rider(db, rid="RID2", name="Sam")
    assert status(db, did=did1) == "rider_cancelled"
    assert status(db, did=did2).startswith("open@")


def test_receipt_status_delivery_declined_is_gone(db):
    delivery(db)
    db.execute("UPDATE public.delivery_summary SET status = 'completed'")  # placeholder to prove 'done' first
    assert status(db, did=1) == "done"
    db.execute("ALTER TABLE public.delivery_summary DROP CONSTRAINT IF EXISTS delivery_summary_status_check")
    db.execute("UPDATE public.delivery_summary SET status = 'declined'")
    assert status(db, did=1) == "gone"


def test_receipt_status_keys_takeaway(db):
    assert status(db, TAKE, "takeaway") == "gone"
    takeaway(db)
    assert status(db, TAKE, "takeaway") == f"open@{hm(db, TAKE, 'takeaway_summary')}"
    ready(db, TAKE, "takeaway")
    assert status(db, TAKE, "takeaway") == f"ready@{hm(db, TAKE, 'takeaway_summary')}"
    db.execute("UPDATE public.takeaway_summary SET status = 'completed'")
    assert status(db, TAKE, "takeaway") == "done"
    db.execute("UPDATE public.takeaway_summary SET status = 'declined'")
    assert status(db, TAKE, "takeaway") == "gone"
    assert status(db, TAKE, "pizza") is None


# ---- receipt snapshot ------------------------------------------------------------------------------------------


def card_copy(db, tcid, mid, state="live", reason=None, number=ORDER):
    db.execute("INSERT INTO public.t_sent_messages (bot_key, tcid, message_id, tuid, subject_type, subject_ref, order_type, kind, rest_ref, "
               "card_status, state, close_reason) VALUES (%s, %s, %s, %s, 'order', %s, 'delivery', 'order_card', 'ELAS', 'accepted', %s, %s)",
               (BOT, tcid, mid, tcid, number, state, reason))


def test_receipt_snapshot_fields_and_reply_to(db):
    delivery(db, rest_confirmation_code=57, customer_address="9 Elm Road")
    did = rider(db)
    link(db)
    link(db, phone=BOB, uid=222, first="Bob")
    card_copy(db, 111, 10)
    card_copy(db, 111, 11)                        # newest live copy wins
    card_copy(db, 111, 12, "closed", "deleted")   # deleted copies are never a reply target
    card_copy(db, 222, 20, "closed", "edited")    # an edited-then-closed copy still exists in the chat
    ready(db)
    snap = fetch_one(db, "SELECT public.t_receipt_snapshot(%s, %s, 'delivery', %s)", (BOT, ORDER, did))
    f = snap["facts"]
    assert snap["status"].startswith("ready@") and snap["rest_ref"] == "ELAS" and snap["dispatch_id"] == did
    assert f["rest_code"] == 57 and f["rest_name"] == "Test Kitchen"
    assert f["rider"] == {"id": "RID1", "name": "Raj"}
    assert f["customer"] == {"address": "9 Elm Road", "phone": "447700900099"}
    assert f["items"] == [
        {"qty": 1, "name": "Naan", "line_total": 3.0, "mods": []},
        {"qty": 2, "name": "Biryani", "line_total": 17.0, "mods": ["Extra spicy", "No nuts"]},
    ]
    assert f["small_order_fee"] == 1.5 and f["total"] == 23.5 and f["notes"] == "No <onions> & extra naan"
    assert f["pay_at_restaurant"] is False
    assert f["ready_by"] == {"label": "Ada", "phone": ADA} and f["ready_at"] is not None
    assert f["pickup_adjusted_by"] is None
    assert [(d["tcid"], d["reply_to"]) for d in snap["destinations"]] == [(111, 11), (222, 20)]


def test_receipt_snapshot_dispatch_none_means_current_rider_and_adjust_is_visible(db):
    delivery(db)
    did = rider(db)
    adjust(db, "(SELECT pickup_time + interval '10 minutes' FROM public.delivery_summary)", phone=BOB)
    snap = fetch_one(db, "SELECT public.t_receipt_snapshot(%s, %s, 'delivery', NULL)", (BOT, ORDER))
    assert snap["dispatch_id"] == did and snap["facts"]["rider"]["id"] == "RID1"
    assert snap["facts"]["pickup_adjusted_by"]["phone"] == BOB and snap["facts"]["pickup_initial"] is not None


def test_receipt_snapshot_takeaway_pay_at_restaurant_and_missing(db):
    takeaway(db, payment="pay_at_rest")
    snap = fetch_one(db, "SELECT public.t_receipt_snapshot(%s, %s, 'takeaway', NULL)", (BOT, TAKE))
    assert snap["facts"]["pay_at_restaurant"] is True and snap["facts"]["rider"] is None and snap["facts"]["customer"] is None
    assert fetch_one(db, "SELECT public.t_receipt_snapshot(%s, 'ELAS-NONE-1', 'delivery', NULL)", (BOT,)) is None
    with pytest.raises(Exception, match="bad order type"):
        fetch_one(db, "SELECT public.t_receipt_snapshot(%s, %s, 'pizza', NULL)", (BOT, TAKE))


# ---- receipt ledger: sent / stale / take -----------------------------------------------------------------------


def sent(db, tcid, mid, did, status_key="open@10:00", number=ORDER):
    return fetch_one(db, "SELECT public.t_receipt_sent(%s, %s, %s, %s, %s, 'delivery', 'ELAS', %s, %s)",
                     (BOT, tcid, mid, tcid, number, did, status_key))


def ledger(db):
    return db.execute("SELECT message_id, state, taken_for, card_status, close_reason, dispatch_id FROM public.t_sent_messages "
                      "WHERE kind = 'receipt' ORDER BY id").fetchall()


def test_receipt_sent_takes_older_copies_any_dispatch_and_ignores_cards(db):
    delivery(db)
    did1 = rider(db)
    card_copy(db, 111, 5)
    assert sent(db, 111, 50, did1)["previous"] == []
    cancel_rider(db, did1)
    did2 = rider(db, rid="RID2", name="Sam")
    out = sent(db, 111, 51, did2, "open@10:00")
    assert [p["message_id"] for p in out["previous"]] == [50]  # older receipt of the old rider: delete
    assert out["status"].startswith("open@")
    assert [(r[0], r[1], r[2]) for r in ledger(db)] == [(50, "taken", "delete"), (51, "live", None)]
    # the order card was not touched
    assert row(db, "SELECT state FROM public.t_sent_messages WHERE kind = 'order_card'")[0] == "live"
    # idempotent on (bot, chat, message)
    assert sent(db, 111, 51, did2)["previous"] == []
    assert len(ledger(db)) == 2


def test_receipt_sent_status_gone_when_order_vanishes(db):
    out = sent(db, 111, 60, 1, "open@10:00", number="ELAS-NONE-1")
    assert out["status"] == "gone"


def test_receipts_stale_after_whatsapp_adjust_and_take_is_exclusive(db):
    delivery(db)
    did = rider(db)
    link(db)
    key = status(db, did=did)
    sent(db, 111, 70, did, key)
    stale = lambda: db.execute("SELECT id, order_number, dispatch_id, authorised, viewer_phone FROM public.t_receipts_stale(%s)", (BOT,)).fetchall()  # noqa: E731
    assert stale() == []
    adjust(db, "(SELECT pickup_time + interval '10 minutes' FROM public.delivery_summary)")  # a WhatsApp +10
    s = stale()
    assert len(s) == 1 and s[0][1:] == (ORDER, did, True, ADA)

    results, errors = [], []

    def worker():
        try:
            with _connect() as c:
                results.append(fetch_one(c, "SELECT public.t_receipts_take(%s, %s, 'delivery')", (BOT, ORDER))["rows"])
        except Exception as e:  # pragma: no cover
            errors.append(e)

    ts = [threading.Thread(target=worker) for _ in range(5)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors
    flat = [r for rows in results for r in rows]
    assert len(flat) == 1  # exactly one worker got the copy
    assert flat[0]["taken_for"] == "edit" and flat[0]["dispatch_id"] == did and flat[0]["authorised"] is True
    assert stale() == []  # claimed: not offered again for 30 s
    # the outcome is recorded with the generic mark function and the copy now shows the new key
    new_key = status(db, did=did)
    db.execute("SELECT public.t_order_card_mark(%s, 'edited', %s, false)", (flat[0]["id"], new_key))
    assert stale() == []
    assert ledger(db)[0][1:4] == ("live", None, new_key)


def test_receipts_stale_when_viewer_revoked_or_claim_expired(db):
    delivery(db)
    did = rider(db)
    link(db)
    sent(db, 111, 80, did, status(db, did=did))
    db.execute("UPDATE public.t_invites SET status = 'revoked'")
    s = db.execute("SELECT authorised FROM public.t_receipts_stale(%s)", (BOT,)).fetchall()
    assert s == [(False,)]
    rows = fetch_one(db, "SELECT public.t_receipts_take(%s, %s, 'delivery')", (BOT, ORDER))["rows"]
    assert rows[0]["authorised"] is False
    assert db.execute("SELECT count(*) FROM public.t_receipts_stale(%s)", (BOT,)).fetchone()[0] == 0
    db.execute("UPDATE public.t_sent_messages SET taken_at = now() - interval '31 seconds'")
    assert db.execute("SELECT count(*) FROM public.t_receipts_stale(%s)", (BOT,)).fetchone()[0] == 1  # re-offered


def test_receipts_stale_ignores_order_cards_and_notices(db):
    delivery(db)
    card_copy(db, 111, 5)  # an order-card copy with a stale status
    fetch_one(db, "SELECT public.t_notice_sent(%s, 111, 99, 111, 'ELAS', %s, 'auto_accepted')", (BOT, ORDER))
    assert db.execute("SELECT count(*) FROM public.t_receipts_stale(%s)", (BOT,)).fetchone()[0] == 0


def test_receipts_older_than_three_days_are_left_alone(db):
    delivery(db)
    did = rider(db)
    link(db)
    sent(db, 111, 95, did, "stale-key")
    assert db.execute("SELECT count(*) FROM public.t_receipts_stale(%s)", (BOT,)).fetchone()[0] == 1
    db.execute("UPDATE public.t_sent_messages SET sent_at = now() - interval '4 days'")
    assert db.execute("SELECT count(*) FROM public.t_receipts_stale(%s)", (BOT,)).fetchone()[0] == 0
    assert fetch_one(db, "SELECT public.job_t_receipt_refresh()") is True and calls(db) == []


def test_receipt_copy_for_cancelled_rider_is_stale_until_edited(db):
    delivery(db)
    did = rider(db)
    link(db)
    sent(db, 111, 90, did, status(db, did=did))
    cancel_rider(db, did)
    assert db.execute("SELECT count(*) FROM public.t_receipts_stale(%s)", (BOT,)).fetchone()[0] == 1
    rows = fetch_one(db, "SELECT public.t_receipts_take(%s, %s, 'delivery')", (BOT, ORDER))["rows"]
    db.execute("SELECT public.t_order_card_mark(%s, 'edited', 'rider_cancelled', false)", (rows[0]["id"],))
    assert db.execute("SELECT count(*) FROM public.t_receipts_stale(%s)", (BOT,)).fetchone()[0] == 0


# ---- refresh job ------------------------------------------------------------------------------------------------


def calls(db):
    return [(u, json.loads(b)) for u, b in db.execute("SELECT url, body FROM public.http_calls ORDER BY id").fetchall()]


def test_job_t_receipt_refresh_posts_only_when_stale(db):
    delivery(db)
    did = rider(db)
    link(db)
    sent(db, 111, 100, did, status(db, did=did))
    assert fetch_one(db, "SELECT public.job_t_receipt_refresh()") is True
    assert calls(db) == []  # nothing stale: the endpoint is not called
    adjust(db, "(SELECT pickup_time + interval '10 minutes' FROM public.delivery_summary)")
    assert fetch_one(db, "SELECT public.job_t_receipt_refresh()") is True
    (url, body), = calls(db)
    assert url.endswith("/telegram/rest-admin/order-alerts")
    assert body["event_type"] == "t_receipt_refresh"
    assert body["receipts"] == [{"order_number": ORDER, "order_type": "delivery"}]
    assert "reminders" not in body and "refreshes" not in body


def test_job_t_receipt_refresh_false_on_non_2xx_and_retries_next_tick(db):
    delivery(db)
    did = rider(db)
    link(db)
    sent(db, 111, 101, did, "stale-key")
    db.execute("UPDATE public.http_stub_status SET status = 500")
    assert fetch_one(db, "SELECT public.job_t_receipt_refresh()") is False
    db.execute("UPDATE public.http_stub_status SET status = 200")
    assert fetch_one(db, "SELECT public.job_t_receipt_refresh()") is True
    assert len(calls(db)) == 2  # the same copy was offered again


# ---- plain notices ------------------------------------------------------------------------------------------------


def test_notice_targets_reply_kinds(db):
    delivery(db)
    did = rider(db)
    link(db)
    link(db, phone=BOB, uid=222, first="Bob")
    card_copy(db, 111, 10)
    card_copy(db, 222, 20, "closed", "deleted")
    sent(db, 111, 50, did)
    t = lambda kind, order=ORDER: db.execute(  # noqa: E731
        "SELECT tcid, tuid, phone, reply_to FROM public.t_notice_targets(%s, 'ELAS', %s, %s) ORDER BY tcid", (BOT, order, kind)).fetchall()
    assert t("card") == [(111, 111, ADA, 10), (222, 222, BOB, None)]
    assert t("receipt") == [(111, 111, ADA, 50), (222, 222, BOB, None)]
    assert t("none") == [(111, 111, ADA, None), (222, 222, BOB, None)]
    assert t("card", None) == [(111, 111, ADA, None), (222, 222, BOB, None)]  # a notice with no order (feedback)


def test_notice_sent_is_closed_audit_row(db):
    delivery(db)
    fetch_one(db, "SELECT public.t_notice_sent(%s, 111, 7, 111, 'ELAS', %s, 'rider_alert')", (BOT, ORDER))
    fetch_one(db, "SELECT public.t_notice_sent(%s, 111, 8, 111, 'ELAS', NULL, 'feedback')", (BOT,))
    fetch_one(db, "SELECT public.t_notice_sent(%s, 111, 8, 111, 'ELAS', NULL, 'feedback')", (BOT,))  # idempotent
    r = db.execute("SELECT subject_type, subject_ref, kind, card_status, state, close_reason, closed_at IS NOT NULL "
                   "FROM public.t_sent_messages ORDER BY message_id").fetchall()
    assert r == [("order", ORDER, "notice", "rider_alert", "closed", "sent", True),
                 ("rest", "ELAS", "notice", "feedback", "closed", "sent", True)]


def test_housekeeping_purges_old_notices(db):
    fetch_one(db, "SELECT public.t_notice_sent(%s, 111, 7, 111, 'ELAS', NULL, 'feedback')", (BOT,))
    fetch_one(db, "SELECT public.t_notice_sent(%s, 111, 8, 111, 'ELAS', NULL, 'feedback')", (BOT,))
    db.execute("UPDATE public.t_sent_messages SET closed_at = now() - interval '31 days' WHERE message_id = 7")
    out = fetch_one(db, "SELECT public.t_housekeeping()")
    assert out["t_sent_messages"] == 1
    assert db.execute("SELECT message_id FROM public.t_sent_messages").fetchall() == [(8,)]


# ---- idempotent re-run, grants ------------------------------------------------------------------------------------

FUNCTIONS = [
    "restaurant_order_ready(text, text, text, text)",
    "restaurant_order_adjust_pickup(text, timestamptz, text, text)",
    "t_order_ready(text, bigint, text, text)",
    "t_order_adjust_pickup(text, bigint, text, int)",
    "t_receipt_status(text, text, integer)",
    "t_receipt_snapshot(text, text, text, integer)",
    "t_receipt_sent(text, bigint, bigint, bigint, text, text, text, integer, text)",
    "t_receipts_stale(text, text, text)",
    "t_receipts_take(text, text, text)",
    "t_notice_targets(text, text, text, text)",
    "t_notice_sent(text, bigint, bigint, bigint, text, text, text)",
    "job_t_receipt_refresh()",
]


@pytest.mark.parametrize("role", ["anon", "authenticated"])
@pytest.mark.parametrize("fn", FUNCTIONS)
def test_functions_revoked_from_anon_and_authenticated(db, role, fn):
    assert fetch_one(db, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, f"public.{fn}")) is False


def test_migration_applies_twice(db):
    from .conftest import migration_sql

    db.execute(migration_sql("restaurant_ready_adjust_notices.sql"))
    db.execute(migration_sql("restaurant_ready_adjust_notices.sql"))
    delivery(db)
    rider(db)
    assert ready(db)["result"] == "ok"


# ---- review fixes: D35 for cancelled copies, stale-send guard, lifecycle lock ------------------------------------------


def test_receipt_sent_replaces_a_cancelled_copy_that_refresh_already_closed_as_edited(db):
    delivery(db)
    did1 = rider(db)
    link(db)
    sent(db, 111, 50, did1, status(db, did=did1))
    cancel_rider(db, did1)
    rows = fetch_one(db, "SELECT public.t_receipts_take(%s, %s, 'delivery')", (BOT, ORDER))["rows"]
    db.execute("SELECT public.t_order_card_mark(%s, 'edited', 'rider_cancelled', true)", (rows[0]["id"],))  # what production does
    assert ledger(db)[0][1:5] == ("closed", None, "rider_cancelled", "edited")
    did2 = rider(db, rid="RID2", name="Sam")
    out = sent(db, 111, 51, did2)
    assert [p["message_id"] for p in out["previous"]] == [50]       # the cancelled message is still on screen: delete it
    assert [(r[0], r[1]) for r in ledger(db)] == [(50, "taken"), (51, "live")]


def test_receipt_sent_for_a_cancelled_or_gone_status_replaces_nothing(db):
    delivery(db)
    did1 = rider(db)
    sent(db, 111, 50, did1, status(db, did=did1))
    cancel_rider(db, did1)
    did2 = rider(db, rid="RID2", name="Sam")
    sent(db, 111, 51, did2)
    out = sent(db, 111, 52, did1)                                    # a delayed event for the cancelled rider
    assert out["previous"] == [] and out["status"] == "rider_cancelled"
    assert [r[1] for r in ledger(db) if r[0] == 51] == ["live"]       # the current rider's copy is untouched
    out = sent(db, 111, 53, 1, number="ELAS-NONE-1")
    assert out["previous"] == [] and out["status"] == "gone"


def test_ready_takes_a_share_lock_on_the_dispatch_so_pickup_cannot_slip_in(db):
    delivery(db)
    did = rider(db)
    a = _connect(autocommit=False)
    try:
        assert fetch_one(a, "SELECT public.restaurant_order_ready(%s, 'delivery', %s, 'test')", (ORDER, ADA))["result"] == "ok"
        errors = []

        def pickup():
            with _connect() as b:
                b.execute("SET lock_timeout = '300ms'")
                try:
                    b.execute("UPDATE public.delivery_dispatch SET status = 'pickedup' WHERE dispatch_id = %s", (did,))
                except Exception as e:
                    errors.append(type(e).__name__)

        t = threading.Thread(target=pickup)
        t.start()
        t.join(5)
        assert errors == ["LockNotAvailable"]                          # blocked until the Ready transaction ends
    finally:
        a.rollback()
        a.close()
