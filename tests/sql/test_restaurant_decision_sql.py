"""Isolated-database tests for ordelo_datamodels/migrations/restaurant_order_decision.sql.

Covers the decide / set_pickup contract, R1-a (a declined delivery is never dispatchable), the "by X" label,
the first-decision-wins race, grants, and that the shared functions still fire the restaurant-update trigger.
Skipped without ORDELO_TEST_DB_URI.
"""

from __future__ import annotations

import threading

import psycopg
import pytest

from .conftest import MIGRATIONS, _connect, fetch_one, migration_sql

pytestmark = pytest.mark.usefixtures("sql_env")

ORDER = "ELAS-TEST-1"
ADMIN = "447700900123"


@pytest.fixture(autouse=True)
def clean(db):
    db.execute("TRUNCATE public.delivery_summary, public.takeaway_summary, public.trigger_log, public.t_invites, public.restaurant_master CASCADE")
    db.execute("INSERT INTO public.restaurant_master (rest_ref, rest_name) VALUES ('ELAS', 'Elas Kitchen')")


def order(db, kind="delivery", number=ORDER):
    db.execute(f"INSERT INTO public.{kind}_summary (order_number) VALUES (%s)", (number,))
    return number


def decide(db, decision="accept", kind="delivery", number=ORDER, phone=ADMIN, channel="whatsapp"):
    return fetch_one(db, "SELECT public.restaurant_order_decide(%s, %s, %s, %s, %s)", (number, kind, decision, phone, channel))


def set_pickup(db, when="2026-10-15 12:15:00+00", kind="delivery", number=ORDER, phone=ADMIN):
    return fetch_one(db, "SELECT public.restaurant_order_set_pickup(%s, %s, %s::timestamptz, %s, 'whatsapp')", (number, kind, when, phone))


def row(db, kind="delivery", number=ORDER):
    return db.execute(
        f"SELECT restaurant_confirmation_status, status, restaurant_admin, pickup_time IS NOT NULL, restaurant_update_dtts IS NOT NULL "
        f"FROM public.{kind}_summary WHERE order_number = %s", (number,)).fetchone()


def add_claimed_invite(db, phone=ADMIN, first_name="Ada"):
    db.execute(
        "INSERT INTO public.t_invites (rest_ref, phone_number, status, claimed_at, telegram_user_id, telegram_chat_id, telegram_first_name) "
        "VALUES ('ELAS', %s, 'claimed', now(), 111, 111, %s)", (phone, first_name))


# ---- R1-a: the CHECK constraint ------------------------------------------------------------------


def test_delivery_status_check_now_allows_declined(db):
    order(db)
    db.execute("UPDATE public.delivery_summary SET status = 'declined'")  # would raise before the migration
    assert row(db)[1] == "declined"


def test_delivery_status_check_still_rejects_nonsense(db):
    order(db)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("UPDATE public.delivery_summary SET status = 'weird'")


# ---- decide ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["delivery", "takeaway"])
def test_accept_ok_sets_status_columns_but_not_lifecycle(db, kind):
    order(db, kind)
    res = decide(db, "accept", kind)
    assert res["result"] == "ok" and res["decision"] == "accept" and res["channel"] == "whatsapp"
    assert res["decided_by"] == "…0123" and res["decided_by_phone"] == ADMIN
    assert row(db, kind) == ("restaurant_accept", "restaurant_unconfirmed", ADMIN, False, True)


def test_delivery_decline_is_terminal_in_the_same_update(db):
    order(db)
    assert decide(db, "decline")["result"] == "ok"
    assert row(db) == ("restaurant_decline", "declined", ADMIN, False, True)   # never 'unassigned': not dispatchable


def test_takeaway_decline_is_terminal(db):
    order(db, "takeaway")
    assert decide(db, "decline", "takeaway")["result"] == "ok"
    assert row(db, "takeaway") == ("restaurant_decline", "declined", ADMIN, False, True)


def test_second_decision_loses_and_reports_who_won(db):
    order(db)
    add_claimed_invite(db, ADMIN, "Ada")
    assert decide(db, "accept", phone=ADMIN)["result"] == "ok"
    res = decide(db, "decline", phone="447700900999")
    assert res["result"] == "already_decided"
    assert res["state"] == "restaurant_accept"
    assert res["decided_by"] == "Ada" and res["decided_by_phone"] == ADMIN
    assert row(db)[0:3] == ("restaurant_accept", "restaurant_unconfirmed", ADMIN)   # the loser changed nothing


def test_decide_after_timeout_is_already_decided(db):
    order(db)
    db.execute("UPDATE public.delivery_summary SET restaurant_confirmation_status = 'restaurant_timedout'")
    res = decide(db, "accept")
    assert res["result"] == "already_decided" and res["state"] == "restaurant_timedout"
    assert res["decided_by"] is None


def test_decide_unknown_order(db):
    assert decide(db, number="NOPE-1") == {"result": "not_found"}


def test_decide_bad_arguments_raise(db):
    order(db)
    with pytest.raises(psycopg.errors.RaiseException):
        decide(db, "maybe")
    with pytest.raises(psycopg.errors.RaiseException):
        decide(db, "accept", kind="pizza")


def test_decide_still_fires_the_restaurant_update_trigger(db):
    order(db)
    db.execute("TRUNCATE public.trigger_log")
    decide(db, "accept")
    assert db.execute("SELECT tbl, order_number, reason FROM public.trigger_log").fetchall() == [
        ("delivery_summary", ORDER, "restaurant_accept")]


def test_concurrent_decisions_have_exactly_one_winner(sql_env):
    c = _connect()
    c.execute("DELETE FROM public.delivery_summary")
    c.execute("INSERT INTO public.delivery_summary (order_number) VALUES ('ELAS-RACE-1')")
    c.close()
    results: list[str] = []
    barrier = threading.Barrier(6)

    def worker(i):
        conn = _connect()
        try:
            barrier.wait()
            results.append(decide(conn, "accept" if i % 2 else "decline", number="ELAS-RACE-1", phone=f"4477009000{i:02d}")["result"])
        finally:
            conn.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["already_decided"] * 5 + ["ok"]


# ---- set_pickup -----------------------------------------------------------------------------------


def test_pickup_after_accept_moves_delivery_to_unassigned(db):
    order(db)
    decide(db, "accept")
    res = set_pickup(db)
    assert res["result"] == "ok" and res["decided_by_phone"] == ADMIN
    assert row(db) == ("restaurant_accept", "unassigned", ADMIN, True, True)


def test_pickup_after_accept_moves_takeaway_to_pickup_confirmed(db):
    order(db, "takeaway")
    decide(db, "accept", "takeaway")
    assert set_pickup(db, kind="takeaway")["result"] == "ok"
    assert row(db, "takeaway") == ("restaurant_accept", "pickup_confirmed", ADMIN, True, True)


def test_pickup_twice_is_already_set_and_keeps_first_time(db):
    order(db)
    decide(db, "accept")
    set_pickup(db, "2026-10-15 12:15:00+00")
    res = set_pickup(db, "2026-10-15 12:25:00+00", phone="447700900999")
    assert res["result"] == "already_set" and res["state"] == "restaurant_accept"
    assert res["pickup_time"].startswith("2026-10-15T12:15:00")
    assert res["decided_by_phone"] == ADMIN


@pytest.mark.parametrize("state", ["restaurant_unconfirmed", "restaurant_decline", "restaurant_timedout", "auto_accept"])
def test_pickup_requires_an_accepted_order(db, state):
    order(db)
    db.execute("UPDATE public.delivery_summary SET restaurant_confirmation_status = %s", (state,))
    res = set_pickup(db)
    assert res["result"] == "not_accepted" and res["state"] == state
    assert row(db)[3] is False                           # pickup_time still NULL


def test_pickup_unknown_order_and_bad_arguments(db):
    assert set_pickup(db, number="NOPE-1") == {"result": "not_found"}
    order(db)
    with pytest.raises(psycopg.errors.RaiseException):
        set_pickup(db, kind="pizza")
    with pytest.raises(psycopg.errors.RaiseException):
        fetch_one(db, "SELECT public.restaurant_order_set_pickup(%s, 'delivery', NULL, %s, 'whatsapp')", (ORDER, ADMIN))


# ---- the label (D19) -------------------------------------------------------------------------------


def label(db, phone):
    return fetch_one(db, "SELECT public.restaurant_admin_label(%s)", (phone,))


def test_label_uses_telegram_first_name_else_last_four_digits(db):
    assert label(db, ADMIN) == "…0123"
    add_claimed_invite(db, ADMIN, "Ada")
    assert label(db, ADMIN) == "Ada"
    assert label(db, "") is None and label(db, None) is None


def test_label_ignores_unclaimed_invites_and_prefers_latest_claim(db):
    db.execute("INSERT INTO public.t_invites (rest_ref, phone_number) VALUES ('ELAS', %s)", (ADMIN,))      # pending
    assert label(db, ADMIN) == "…0123"
    db.execute(
        "INSERT INTO public.t_invites (rest_ref, phone_number, status, claimed_at, telegram_user_id, telegram_chat_id, telegram_first_name) "
        "VALUES ('ELAS', %s, 'claimed', now() - interval '2 days', 1, 1, 'Old')", (ADMIN,))
    db.execute(
        "INSERT INTO public.t_invites (rest_ref, phone_number, status, claimed_at, telegram_user_id, telegram_chat_id, telegram_first_name) "
        "VALUES ('ELAS', %s, 'claimed', now(), 2, 2, 'New')", (ADMIN,))
    assert label(db, ADMIN) == "New"


# ---- security + repeatability -----------------------------------------------------------------------


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_public_roles_cannot_call(db, role):
    order(db)
    db.execute(f"SET ROLE {role}")
    try:
        for sql, args in [
            ("SELECT public.restaurant_order_decide(%s, 'delivery', 'accept', %s, 'x')", (ORDER, ADMIN)),
            ("SELECT public.restaurant_order_set_pickup(%s, 'delivery', now(), %s, 'x')", (ORDER, ADMIN)),
            ("SELECT public.restaurant_admin_label(%s)", (ADMIN,)),
        ]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db.execute(sql, args)
    finally:
        db.execute("RESET ROLE")
    assert row(db)[0] == "restaurant_unconfirmed"


def test_migration_is_repeatable(db):
    order(db)
    decide(db, "accept")
    db.execute(migration_sql("restaurant_order_decision.sql"))
    assert row(db)[0] == "restaurant_accept"
    assert (MIGRATIONS / "restaurant_order_decision.sql").exists()
