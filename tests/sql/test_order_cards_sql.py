"""Isolated-database tests for ordelo_datamodels/telegram/t_order_alerts.sql.

Covers the status mapping, destinations (D14), the snapshot, the ledger functions (send / take / mark, races),
the sweep (seed, cancel, collapse, POST, mark only on 2xx, stale refreshes), housekeeping, and grants.
Skipped without ORDELO_TEST_DB_URI.
"""

from __future__ import annotations

import json
import threading

import psycopg
import pytest

from .conftest import _connect, fetch_one

pytestmark = pytest.mark.usefixtures("sql_env")

BOT = "rest_admin"
ORDER = "ELAS-CEKT-22"
ADA, BOB = "447700900001", "447700900002"


@pytest.fixture(autouse=True)
def clean(db):
    db.execute(
        "TRUNCATE public.delivery_summary, public.takeaway_summary, public.t_invites, public.restaurant_master, "
        "public.t_order_alerts, public.t_sent_messages, public.t_inbox, public.food_order, public.order_item, "
        "public.http_calls CASCADE"
    )
    db.execute("UPDATE public.http_stub_status SET status = 200")
    db.execute("DELETE FROM public.ordelo_config WHERE config_key LIKE '%TGRAM_ORDER_ALERT%'")
    db.execute(
        "INSERT INTO public.ordelo_config (config_key, config_value) VALUES ('TGRAM_ORDER_ALERT_OFFSETS_SECS', '0,15,30,45')"
    )
    db.execute("INSERT INTO public.restaurant_master (rest_ref, rest_name, admins) VALUES ('ELAS', 'Elas Kitchen', %s)", ([ADA, BOB],))


def link(db, phone=ADA, uid=111, first="Ada", status="claimed", rest="ELAS"):
    db.execute(
        "INSERT INTO public.t_invites (rest_ref, phone_number, status, claimed_at, telegram_user_id, telegram_chat_id, telegram_first_name) "
        "VALUES (%s, %s, %s, now(), %s, %s, %s)", (rest, phone, status, uid, uid, first))


def order(db, number=ORDER, kind="delivery", age="0 seconds", **cols):
    db.execute(f"INSERT INTO public.{kind}_summary (order_number, dtts) VALUES (%s, now() - %s::interval)", (number, age))
    for k, v in cols.items():
        db.execute(f"UPDATE public.{kind}_summary SET {k} = %s WHERE order_number = %s", (v, number))
    db.execute("INSERT INTO public.food_order (order_id, order_number, total_price) VALUES (%s, %s, 23.5) ON CONFLICT DO NOTHING", (number, number))
    db.execute("INSERT INTO public.order_item (order_id, product_name, quantity) VALUES (%s, 'Naan', 1), (%s, 'Biryani', 2)", (number, number))
    return number


def snapshot(db, number=ORDER, kind="delivery"):
    return fetch_one(db, "SELECT public.t_order_card_snapshot(%s, %s, %s)", (BOT, number, kind))


def sent(db, tcid, mid, number=ORDER, kind="delivery", status="awaiting", tuid="same"):
    return fetch_one(
        db, "SELECT public.t_order_card_sent(%s, %s, %s, %s, %s, %s, 'ELAS', %s)",
        (BOT, tcid, mid, tcid if tuid == "same" else tuid, number, kind, status))


def take(db, number=ORDER, kind="delivery"):
    return fetch_one(db, "SELECT public.t_order_cards_take(%s, %s, %s)", (BOT, number, kind))["rows"]


def ledger(db):
    return db.execute("SELECT message_id, state, taken_for, card_status, close_reason FROM public.t_sent_messages ORDER BY id").fetchall()


# ---- status mapping ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rcs,pickup,expected",
    [
        ("restaurant_unconfirmed", None, "awaiting"),
        ("restaurant_accept", None, "accepted"),
        ("restaurant_accept", "2026-01-01 12:00+00", "pickup_set"),
        ("restaurant_pickuptime_adjusted", "2026-01-01 12:00+00", "pickup_set"),
        ("restaurant_decline", None, "declined"),
        ("auto_decline", None, "declined"),
        ("auto_accept", "2026-01-01 12:00+00", "auto_accepted"),
        ("restaurant_timedout", "2026-01-01 12:00+00", "auto_accepted"),
        ("restaurant_timedout", None, "awaiting"),
        (None, None, None),
    ],
)
def test_card_status(db, rcs, pickup, expected):
    assert fetch_one(db, "SELECT public.t_order_card_status(%s, %s::timestamptz)", (rcs, pickup)) == expected


# ---- destinations (D14) -----------------------------------------------------------------------------------------


def dests(db, rest="ELAS"):
    return db.execute("SELECT tcid, tuid, phone, label FROM public.t_order_card_destinations(%s, %s) ORDER BY tcid", (BOT, rest)).fetchall()


def test_destinations_need_claimed_invite_and_admin_phone(db):
    link(db, ADA, 111)
    link(db, BOB, 222, "Bob", status="pending")  # not claimed
    link(db, "447700900099", 333, "Eve")  # claimed but not in admins
    assert dests(db) == [(111, 111, ADA, "Ada")]


def test_destinations_admins_compared_by_digits(db):
    db.execute("UPDATE public.restaurant_master SET admins = %s", (["+44 7700 900001"],))
    link(db, ADA, 111)
    assert [d[0] for d in dests(db)] == [111]


def test_destinations_other_restaurant_excluded(db):
    db.execute("INSERT INTO public.restaurant_master (rest_ref, rest_name, admins) VALUES ('WREN', 'Wren', %s)", ([ADA],))
    link(db, ADA, 111, rest="WREN")
    assert dests(db, "ELAS") == [] and len(dests(db, "WREN")) == 1


# ---- snapshot ---------------------------------------------------------------------------------------------------


def test_snapshot_unknown_order_is_null(db):
    assert snapshot(db, "NOPE-1") is None


def test_snapshot_awaiting_shape(db):
    link(db)
    order(db)
    s = snapshot(db)
    assert s["status"] == "awaiting" and s["rest_ref"] == "ELAS" and s["decided_by"] is None and s["pickup_at"] is None
    f = s["facts"]
    assert f["order_number"] == ORDER and f["order_type"] == "delivery" and f["rest_name"] == "Test Kitchen"
    assert f["total"] == "£23.50" and f["items"] == ["2x Biryani", "1x Naan"]
    assert s["destinations"] == [{"tcid": 111, "tuid": 111, "phone": ADA, "label": "Ada"}]


def test_snapshot_decided_by_label_and_pickup(db):
    link(db)
    order(db, restaurant_confirmation_status="restaurant_accept", restaurant_admin=ADA, pickup_time="2026-01-01 12:15+00")
    s = snapshot(db)
    assert s["status"] == "pickup_set" and s["decided_by"] == {"label": "Ada", "phone": ADA}
    assert s["pickup_at"].startswith("2026-01-01T12:15")


def test_snapshot_takeaway(db):
    order(db, "ELAS-TK-1", "takeaway")
    s = snapshot(db, "ELAS-TK-1", "takeaway")
    assert s["facts"]["order_type"] == "takeaway"
    assert snapshot(db, "ELAS-TK-1", "delivery") is None  # wrong type = not found


def test_snapshot_order_without_food_order_row(db):
    db.execute("INSERT INTO public.delivery_summary (order_number) VALUES ('ELAS-X-1')")
    s = snapshot(db, "ELAS-X-1")
    assert s["facts"]["total"] == "" and s["facts"]["items"] == []


# ---- ledger: sent / take / mark ---------------------------------------------------------------------------------


def test_sent_records_and_reports_order_status(db):
    order(db)
    r = sent(db, 111, 1)
    assert r == {"previous": [], "order_status": "awaiting"}
    assert ledger(db) == [(1, "live", None, "awaiting", None)]


def test_sent_takes_only_older_copies_in_same_chat(db):
    order(db)
    sent(db, 111, 1)
    sent(db, 222, 5)  # other chat: untouched
    r = sent(db, 111, 2)
    assert [p["message_id"] for p in r["previous"]] == [1]
    assert ledger(db) == [(1, "taken", "delete", "awaiting", None), (5, "live", None, "awaiting", None), (2, "live", None, "awaiting", None)]


def test_sent_never_takes_a_newer_copy(db):
    """Two reminders in flight must not delete each other: a copy only takes copies recorded BEFORE it."""
    order(db)
    sent(db, 111, 1)  # ledger id a
    r = sent(db, 111, 2)  # ledger id b > a, takes a
    assert [p["message_id"] for p in r["previous"]] == [1]
    again = sent(db, 111, 1)  # the first call is replayed: same row a, and b is NEWER than a
    assert again["previous"] == []
    assert ledger(db) == [(1, "taken", "delete", "awaiting", None), (2, "live", None, "awaiting", None)]


def test_sent_reports_decided_mid_send(db):
    order(db, restaurant_confirmation_status="restaurant_accept", restaurant_admin=ADA)
    assert sent(db, 111, 1)["order_status"] == "accepted"
    assert sent(db, 111, 2, number="NOPE-1")["order_status"] == "gone"


def test_take_returns_nothing_when_up_to_date(db):
    link(db)
    order(db)
    sent(db, 111, 1)
    assert take(db) == []


def test_take_after_status_change_then_mark_edited_back_to_live(db):
    link(db)
    order(db)
    sent(db, 111, 1)
    db.execute("UPDATE public.delivery_summary SET restaurant_confirmation_status = 'restaurant_accept', restaurant_admin = %s", (ADA,))
    rows = take(db)
    assert len(rows) == 1 and rows[0]["taken_for"] == "edit" and rows[0]["authorised"] is True and rows[0]["viewer_phone"] == ADA
    assert take(db) == []  # claimed: a second pass gets nothing
    db.execute("SELECT public.t_order_card_mark(%s, 'edited', 'accepted', false)", (rows[0]["id"],))
    assert ledger(db) == [(1, "live", None, "accepted", None)]
    assert take(db) == []


def test_terminal_mark_closes(db):
    link(db)
    order(db, restaurant_confirmation_status="restaurant_decline", restaurant_admin=ADA)
    sent(db, 111, 1)
    rows = take(db)
    db.execute("SELECT public.t_order_card_mark(%s, 'edited', 'declined', true)", (rows[0]["id"],))
    assert ledger(db) == [(1, "closed", None, "declined", "edited")]


def test_revoked_viewer_is_taken_unauthorised(db):
    link(db)
    order(db)
    sent(db, 111, 1)
    db.execute("UPDATE public.t_invites SET status = 'revoked'")
    rows = take(db)
    assert len(rows) == 1 and rows[0]["authorised"] is False and rows[0]["viewer_phone"] is None


def test_admin_removed_from_restaurant_is_unauthorised(db):
    link(db)
    order(db)
    sent(db, 111, 1)
    db.execute("UPDATE public.restaurant_master SET admins = '{}'")
    assert take(db)[0]["authorised"] is False


def test_vanished_order_keeps_viewer_authorised(db):
    link(db)
    order(db)
    sent(db, 111, 1)
    db.execute("DELETE FROM public.delivery_summary")
    rows = take(db)
    assert len(rows) == 1 and rows[0]["authorised"] is True


def test_stuck_claim_is_reoffered_after_30_seconds_and_keeps_taken_for(db):
    link(db)
    order(db)
    sent(db, 111, 1)
    r = sent(db, 111, 2)
    prev = r["previous"][0]["id"]
    assert take(db) == []  # a fresh 'delete' claim is not offered
    db.execute("UPDATE public.t_sent_messages SET taken_at = now() - interval '20 seconds' WHERE id = %s", (prev,))
    assert take(db) == []  # still within the claim window
    db.execute("UPDATE public.t_sent_messages SET taken_at = now() - interval '40 seconds' WHERE id = %s", (prev,))
    rows = take(db)
    assert [(x["id"], x["taken_for"]) for x in rows] == [(prev, "delete")]


def test_mark_deleted_and_gone_close(db):
    order(db)
    sent(db, 111, 1)
    sent(db, 111, 2)
    sent(db, 111, 3)
    ids = [r[0] for r in db.execute("SELECT id FROM public.t_sent_messages WHERE state = 'taken' ORDER BY id").fetchall()]
    db.execute("SELECT public.t_order_card_mark(%s, 'deleted', NULL, true)", (ids[0],))
    db.execute("SELECT public.t_order_card_mark(%s, 'gone', NULL, false)", (ids[1],))
    assert [r[1:] for r in ledger(db)[:2]] == [("closed", None, "awaiting", "deleted"), ("closed", None, "awaiting", "gone")]
    db.execute("SELECT public.t_order_card_mark(%s, 'deleted', NULL, true)", (ids[0],))  # idempotent


def test_mark_rejects_bad_outcome(db):
    with pytest.raises(psycopg.errors.RaiseException):
        db.execute("SELECT public.t_order_card_mark(1, 'exploded', NULL, true)")


def test_concurrent_take_gives_each_copy_to_one_worker(sql_env, db):
    link(db)
    order(db)
    for m in range(1, 9):
        db.execute("INSERT INTO public.t_sent_messages (bot_key, tcid, message_id, tuid, subject_type, subject_ref, order_type, kind, rest_ref, card_status) "
                   "VALUES (%s, %s, 1, %s, 'order', %s, 'delivery', 'order_card', 'ELAS', 'awaiting')", (BOT, 1000 + m, 1000 + m, ORDER))
    db.execute("UPDATE public.delivery_summary SET restaurant_confirmation_status = 'restaurant_accept', restaurant_admin = %s", (ADA,))
    results, errors = [], []

    def worker():
        try:
            c = _connect()
            results.append([r["id"] for r in take_on(c)])
            c.close()
        except Exception as e:  # pragma: no cover
            errors.append(e)

    def take_on(c):
        return fetch_one(c, "SELECT public.t_order_cards_take(%s, %s, %s)", (BOT, ORDER, "delivery"))["rows"]

    ts = [threading.Thread(target=worker) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors
    flat = [i for r in results for i in r]
    assert len(flat) == len(set(flat))  # nobody got the same copy twice
    assert len(set(flat)) == 8  # and all were claimed


# ---- sweep ------------------------------------------------------------------------------------------------------


def alerts(db):
    return db.execute("SELECT order_number, offset_secs, n, of_n, status FROM public.t_order_alerts ORDER BY offset_secs").fetchall()


def calls(db):
    return [(u, json.loads(b)) for u, b in db.execute("SELECT url, body FROM public.http_calls ORDER BY id").fetchall()]


def sweep(db):
    return fetch_one(db, "SELECT public.job_t_order_alerts()")


def test_sweep_seeds_one_checkpoint_per_offset_and_posts_first_reminder(db):
    link(db)
    order(db, age="2 seconds")
    assert sweep(db) is True
    a = alerts(db)
    assert [(x[1], x[2], x[3]) for x in a] == [(0, 1, 4), (15, 2, 4), (30, 3, 4), (45, 4, 4)]
    assert [x[4] for x in a] == ["sent", "pending", "pending", "pending"]
    (url, body), = calls(db)
    assert url.endswith("/telegram/rest-admin/order-alerts") and url.startswith("https://agent.ordelo.app")
    assert body["event_type"] == "t_order_alerts"
    assert body["reminders"] == [{"order_number": ORDER, "order_type": "delivery", "n": 1, "of": 4}] and body["refreshes"] == []


def test_sweep_is_quiet_when_nothing_due(db):
    link(db)
    order(db, age="0 seconds")
    sweep(db)  # first reminder (offset 0)
    db.execute("DELETE FROM public.http_calls")
    sweep(db)
    assert calls(db) == []


def test_sweep_uses_app_url_config(db):
    link(db)
    order(db)
    db.execute("INSERT INTO public.ordelo_config (config_key, config_value) VALUES ('ORDELO_APP_URL', 'https://x.example/') ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value")
    try:
        sweep(db)
        assert calls(db)[0][0] == "https://x.example/telegram/rest-admin/order-alerts"
    finally:
        db.execute("DELETE FROM public.ordelo_config WHERE config_key = 'ORDELO_APP_URL'")


def test_sweep_collapses_after_an_outage_to_largest_offset(db):
    link(db)
    order(db, age="40 seconds")  # 0, 15, 30 due; 45 not yet
    sweep(db)
    (_, body), = calls(db)
    assert body["reminders"] == [{"order_number": ORDER, "order_type": "delivery", "n": 3, "of": 4}]
    st = {x[1]: x[4] for x in alerts(db)}
    assert st == {0: "superseded", 15: "superseded", 30: "sent", 45: "pending"}


def test_sweep_leaves_everything_pending_on_non_2xx(db):
    link(db)
    order(db, age="40 seconds")
    db.execute("UPDATE public.http_stub_status SET status = 503")
    assert sweep(db) is False
    assert {x[4] for x in alerts(db)} == {"pending"}
    db.execute("UPDATE public.http_stub_status SET status = 200")
    assert sweep(db) is True
    assert "sent" in {x[4] for x in alerts(db)}


def test_sweep_cancels_when_order_decided(db):
    link(db)
    order(db, age="2 seconds")
    sweep(db)
    db.execute("UPDATE public.delivery_summary SET restaurant_confirmation_status = 'restaurant_accept', restaurant_admin = %s", (ADA,))
    sweep(db)
    assert [x[4] for x in alerts(db)] == ["sent", "cancelled", "cancelled", "cancelled"]


def test_sweep_does_not_seed_without_destination_or_for_old_or_decided_orders(db):
    db.execute("INSERT INTO public.restaurant_master (rest_ref, rest_name, admins) VALUES ('WREN', 'Wren', %s)", ([ADA],))
    order(db, "WREN-A-1", age="2 seconds")  # nobody linked to WREN
    link(db)
    order(db, "ELAS-B-1", age="20 minutes")  # too old
    order(db, "ELAS-C-1", age="2 seconds", restaurant_confirmation_status="restaurant_accept")
    sweep(db)
    assert alerts(db) == [] and calls(db) == []


def test_sweep_takeaway_orders_and_per_restaurant_offsets(db):
    link(db)
    db.execute("INSERT INTO public.ordelo_config (config_key, config_value) VALUES ('ELAS_TGRAM_ORDER_ALERT_OFFSETS_SECS', '0, 60')")
    order(db, "ELAS-TK-9", "takeaway", age="1 second")
    sweep(db)
    assert [(x[1], x[3]) for x in alerts(db)] == [(0, 2), (60, 2)]
    assert calls(db)[0][1]["reminders"][0]["order_type"] == "takeaway"


def test_sweep_blank_offsets_turns_reminders_off(db):
    link(db)
    db.execute("UPDATE public.ordelo_config SET config_value = '' WHERE config_key = 'TGRAM_ORDER_ALERT_OFFSETS_SECS'")
    order(db)
    sweep(db)
    assert alerts(db) == []


def test_sweep_sends_refreshes_for_stale_cards(db):
    link(db)
    order(db, age="400 seconds")
    sent(db, 111, 1)
    db.execute("UPDATE public.delivery_summary SET restaurant_confirmation_status = 'restaurant_accept', restaurant_admin = %s", (ADA,))
    sweep(db)
    (_, body), = calls(db)
    assert body["reminders"] == [] and body["refreshes"] == [{"order_number": ORDER, "order_type": "delivery"}]
    # the sweep only reports; the cards stay 'live' until a refresh takes them
    assert ledger(db)[0][1] == "live"


def test_sweep_refresh_list_is_distinct_and_capped(db):
    link(db)
    for i in range(60):
        n = f"ELAS-S-{i}"
        order(db, n, age="400 seconds", restaurant_confirmation_status="restaurant_accept", restaurant_admin=ADA)
        sent(db, 111, 100 + i, number=n)
        sent(db, 222, 500 + i, number=n)  # second stale copy of the same order must not repeat the order
    sweep(db)
    refreshes = calls(db)[0][1]["refreshes"]
    assert len(refreshes) == 50 and len({r["order_number"] for r in refreshes}) == 50


# ---- housekeeping -----------------------------------------------------------------------------------------------


def test_housekeeping_purges_by_retention(db):
    order(db)
    db.execute("INSERT INTO public.t_inbox (bot_key, update_id, kind, status, received_at) VALUES (%s, 1, 'message', 'done', now() - interval '8 days'), (%s, 2, 'message', 'done', now())", (BOT, BOT))
    db.execute(
        "INSERT INTO public.t_sent_messages (bot_key, tcid, message_id, subject_type, subject_ref, kind, state, closed_at) VALUES "
        "(%s, 1, 1, 'order', 'A', 'order_card', 'closed', now() - interval '31 days'), "
        "(%s, 1, 2, 'order', 'B', 'order_card', 'closed', now() - interval '1 day'), "
        "(%s, 1, 3, 'order', 'C', 'order_card', 'live', NULL)", (BOT, BOT, BOT))
    db.execute(
        "INSERT INTO public.t_order_alerts (order_number, order_type, rest_ref, offset_secs, n, of_n, due_at, status, created_at) VALUES "
        "('A', 'delivery', 'ELAS', 0, 1, 1, now(), 'sent', now() - interval '40 days'), "
        "('B', 'delivery', 'ELAS', 0, 1, 1, now(), 'pending', now() - interval '40 days'), "
        "('C', 'delivery', 'ELAS', 0, 1, 1, now(), 'sent', now())")
    counts = fetch_one(db, "SELECT public.t_housekeeping()")
    assert counts == {"t_inbox": 1, "t_sent_messages": 1, "t_order_alerts": 1}
    assert fetch_one(db, "SELECT count(*) FROM public.t_inbox") == 1
    assert fetch_one(db, "SELECT count(*) FROM public.t_sent_messages") == 2
    assert fetch_one(db, "SELECT count(*) FROM public.t_order_alerts") == 2  # the old PENDING one stays


def test_housekeeping_bad_config_falls_back_to_defaults(db):
    db.execute("UPDATE public.ordelo_config SET config_value = 'soon' WHERE config_key IN ('TGRAM_INBOX_RETENTION_DAYS', 'TGRAM_LEDGER_RETENTION_DAYS')")
    try:
        assert fetch_one(db, "SELECT public.t_housekeeping()") == {"t_inbox": 0, "t_sent_messages": 0, "t_order_alerts": 0}
    finally:
        db.execute("UPDATE public.ordelo_config SET config_value = '7' WHERE config_key = 'TGRAM_INBOX_RETENTION_DAYS'")
        db.execute("UPDATE public.ordelo_config SET config_value = '30' WHERE config_key = 'TGRAM_LEDGER_RETENTION_DAYS'")


# ---- security / repeatability -----------------------------------------------------------------------------------

FUNCTIONS = [
    "t_order_card_status(text, timestamptz)", "t_order_card_row(text, text)", "t_order_card_destinations(text, text)",
    "t_order_card_snapshot(text, text, text)", "t_order_card_sent(text, bigint, bigint, bigint, text, text, text, text)",
    "t_order_cards_stale(text, text, text)", "t_order_cards_take(text, text, text)", "t_order_card_mark(bigint, text, text, boolean)",
    "job_t_order_alerts()", "t_housekeeping()",
]


@pytest.mark.parametrize("fn", FUNCTIONS)
@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_functions_not_executable_by_api_roles(db, fn, role):
    assert fetch_one(db, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, f"public.{fn}")) is False


@pytest.mark.parametrize("table", ["t_order_alerts", "t_sent_messages"])
def test_rls_enabled(db, table):
    assert fetch_one(db, "SELECT relrowsecurity FROM pg_class WHERE oid = %s::regclass", (f"public.{table}",)) is True


def test_migration_is_repeatable(db):
    from .conftest import migration_sql

    db.execute(migration_sql("t_order_alerts.sql"))
    db.execute(migration_sql("t_order_alerts.sql"))
    assert fetch_one(db, "SELECT count(*) FROM public.ordelo_config WHERE config_key = 'TGRAM_ORDER_ALERT_OFFSETS_SECS'") == 1
