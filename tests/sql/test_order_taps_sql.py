"""Isolated-database tests for the Telegram tap functions in restaurant_order_decision.sql
(t_order_admin_phone, t_order_decide, t_order_set_pickup): D14 authorisation by tuid, first decision wins across
people and channels, pickup = order time + minutes, and the decline rules. Skipped without ORDELO_TEST_DB_URI.
"""

from __future__ import annotations

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
    db.execute("TRUNCATE public.delivery_summary, public.takeaway_summary, public.trigger_log, public.t_invites, public.restaurant_master CASCADE")
    db.execute("INSERT INTO public.restaurant_master (rest_ref, rest_name, admins) VALUES ('ELAS', 'Elas Kitchen', %s)", ([ADA, BOB],))
    link(db, ADA, 111, "Ada")


def link(db, phone, uid, first, status="claimed", rest="ELAS"):
    db.execute(
        "INSERT INTO public.t_invites (rest_ref, phone_number, status, claimed_at, telegram_user_id, telegram_chat_id, telegram_first_name) "
        "VALUES (%s, %s, %s, now(), %s, %s, %s)", (rest, phone, status, uid, uid, first))


def order(db, kind="delivery", number=ORDER, **cols):
    db.execute(f"INSERT INTO public.{kind}_summary (order_number, dtts) VALUES (%s, '2026-10-15 12:00:00+00')", (number,))
    for k, v in cols.items():
        db.execute(f"UPDATE public.{kind}_summary SET {k} = %s WHERE order_number = %s", (v, number))
    return number


def decide(db, tuid=111, decision="accept", kind="delivery", number=ORDER):
    return fetch_one(db, "SELECT public.t_order_decide(%s, %s, %s, %s, %s)", (BOT, tuid, number, kind, decision))


def pickup(db, tuid=111, minutes=15, kind="delivery", number=ORDER):
    return fetch_one(db, "SELECT public.t_order_set_pickup(%s, %s, %s, %s, %s)", (BOT, tuid, number, kind, minutes))


def state(db, kind="delivery", number=ORDER):
    return db.execute(
        f"SELECT restaurant_confirmation_status, status, restaurant_admin, pickup_time FROM public.{kind}_summary WHERE order_number = %s",
        (number,)).fetchone()


# ---- authorisation (D14) ----------------------------------------------------------------------------------------


def test_linked_admin_can_accept(db):
    order(db)
    r = decide(db)
    assert r["result"] == "ok" and r["decided_by"] == "Ada" and r["decided_by_phone"] == ADA
    assert state(db)[:3] == ("restaurant_accept", "restaurant_unconfirmed", ADA)


@pytest.mark.parametrize("who", ["stranger", "pending", "revoked", "other_restaurant", "phone_not_admin"])
def test_unauthorised_tap_changes_nothing(db, who):
    order(db)
    db.execute("TRUNCATE public.t_invites")
    if who == "pending":
        link(db, ADA, 111, "Ada", status="pending")
    elif who == "revoked":
        link(db, ADA, 111, "Ada", status="revoked")
    elif who == "other_restaurant":
        db.execute("INSERT INTO public.restaurant_master (rest_ref, rest_name, admins) VALUES ('WREN', 'Wren', %s)", ([ADA],))
        link(db, ADA, 111, "Ada", rest="WREN")
    elif who == "phone_not_admin":
        link(db, "447700900099", 111, "Eve")
    assert decide(db) == {"result": "not_authorised"}
    assert pickup(db) == {"result": "not_authorised"}
    assert state(db) == ("restaurant_unconfirmed", "restaurant_unconfirmed", None, None)


def test_authorisation_follows_the_admins_list_and_the_invite_status(db):
    order(db, "delivery", "ELAS-A-1")
    order(db, "delivery", "ELAS-A-2")
    db.execute("UPDATE public.restaurant_master SET admins = '{}'")
    assert decide(db, number="ELAS-A-1")["result"] == "not_authorised"
    db.execute("UPDATE public.restaurant_master SET admins = %s", ([ADA],))
    assert decide(db, number="ELAS-A-1")["result"] == "ok"
    db.execute("UPDATE public.t_invites SET status = 'revoked'")
    assert decide(db, number="ELAS-A-2")["result"] == "not_authorised"


def test_authorisation_uses_the_user_not_the_chat(db):
    """D27: a button pressed in a group (different chat id) is authorised by the user id alone."""
    order(db)
    db.execute("UPDATE public.t_invites SET telegram_chat_id = 111")  # invite chat is the private chat; tap comes from elsewhere
    assert decide(db, tuid=111)["result"] == "ok"
    order(db, "delivery", "ELAS-B-1")
    assert decide(db, tuid=-100, number="ELAS-B-1")["result"] == "not_authorised"  # a chat id is not a user


def test_admins_with_formatting_are_matched_by_digits(db):
    order(db)
    db.execute("UPDATE public.restaurant_master SET admins = %s", (["+44 7700 900001"],))
    assert decide(db)["result"] == "ok"


def test_not_found_before_authorisation(db):
    db.execute("TRUNCATE public.t_invites")
    assert decide(db, number="NOPE-1") == {"result": "not_found"}
    assert pickup(db, number="NOPE-1") == {"result": "not_found"}


def test_bad_arguments_raise(db):
    order(db)
    with pytest.raises(psycopg.errors.RaiseException):
        decide(db, kind="pizza")
    with pytest.raises(psycopg.errors.RaiseException):
        decide(db, decision="maybe")
    for minutes in (0, -5, 121, None):
        with pytest.raises(psycopg.errors.RaiseException):
            pickup(db, minutes=minutes)


# ---- first decision wins ----------------------------------------------------------------------------------------


def test_second_admin_is_told_who_decided(db):
    link(db, BOB, 222, "Bob")
    order(db)
    assert decide(db, 111)["result"] == "ok"
    r = decide(db, 222)
    assert r["result"] == "already_decided" and r["decided_by"] == "Ada" and r["decided_by_phone"] == ADA
    assert r["state"] == "restaurant_accept"
    assert state(db)[2] == ADA


def test_whatsapp_decision_beats_a_later_telegram_tap(db):
    order(db)
    db.execute("SELECT public.restaurant_order_decide(%s, 'delivery', 'accept', %s, 'whatsapp')", (ORDER, BOB))
    r = decide(db, 111, "decline")
    assert r["result"] == "already_decided" and r["decided_by_phone"] == BOB
    assert state(db)[:2] == ("restaurant_accept", "restaurant_unconfirmed")


def test_concurrent_taps_have_exactly_one_winner(sql_env, db):
    for i in range(5):
        link(db, f"4477009100{i}0", 300 + i, f"P{i}")
    db.execute("UPDATE public.restaurant_master SET admins = admins || %s", ([f"4477009100{i}0" for i in range(5)],))
    order(db)
    results, errors = [], []
    barrier = threading.Barrier(6)

    def tap(uid, decision):
        try:
            c = _connect()
            barrier.wait()
            results.append(fetch_one(c, "SELECT public.t_order_decide(%s, %s, %s, 'delivery', %s)", (BOT, uid, ORDER, decision))["result"])
            c.close()
        except Exception as e:  # pragma: no cover
            errors.append(e)

    ts = [threading.Thread(target=tap, args=(111, "accept"))] + [
        threading.Thread(target=tap, args=(300 + i, "decline" if i % 2 else "accept")) for i in range(5)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors
    assert sorted(results) == ["already_decided"] * 5 + ["ok"]


# ---- decline ----------------------------------------------------------------------------------------------------


def test_decline_delivery_is_terminal_and_fires_the_webhook_trigger(db):
    order(db)
    assert decide(db, decision="decline")["result"] == "ok"
    assert state(db)[:2] == ("restaurant_decline", "declined")
    assert db.execute("SELECT reason FROM public.trigger_log ORDER BY id DESC LIMIT 1").fetchone()[0] == "restaurant_decline"


def test_decline_takeaway(db):
    order(db, "takeaway", "ELAS-TK-1")
    assert decide(db, decision="decline", kind="takeaway", number="ELAS-TK-1")["result"] == "ok"
    assert state(db, "takeaway", "ELAS-TK-1")[:2] == ("restaurant_decline", "declined")


# ---- pickup -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("minutes", [5, 15, 25])
def test_pickup_is_order_time_plus_minutes(db, minutes):
    order(db)
    decide(db)
    r = pickup(db, minutes=minutes)
    assert r["result"] == "ok"
    assert fetch_one(db, "SELECT pickup_time = '2026-10-15 12:00:00+00'::timestamptz + make_interval(mins => %s) FROM public.delivery_summary", (minutes,)) is True
    assert state(db)[1] == "unassigned"  # dispatchable only after the pickup time is set


def test_pickup_takeaway(db):
    order(db, "takeaway", "ELAS-TK-1")
    decide(db, kind="takeaway", number="ELAS-TK-1")
    assert pickup(db, kind="takeaway", number="ELAS-TK-1")["result"] == "ok"
    assert state(db, "takeaway", "ELAS-TK-1")[1] == "pickup_confirmed"


def test_pickup_states(db):
    order(db)
    assert pickup(db)["result"] == "not_accepted"  # still unconfirmed
    decide(db)
    assert pickup(db, minutes=5)["result"] == "ok"
    r = pickup(db, minutes=25)
    assert r["result"] == "already_set" and r["pickup_time"].startswith("2026-10-15T12:05")
    order(db, "delivery", "ELAS-D-1")
    decide(db, decision="decline", number="ELAS-D-1")
    assert pickup(db, number="ELAS-D-1")["result"] == "not_accepted"


# ---- security ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fn",
    ["t_order_admin_phone(text, bigint, text)", "t_order_decide(text, bigint, text, text, text)", "t_order_set_pickup(text, bigint, text, text, int)"],
)
@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_functions_not_executable_by_api_roles(db, fn, role):
    assert fetch_one(db, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, f"public.{fn}")) is False


def test_migration_is_repeatable(db):
    from .conftest import migration_sql

    db.execute(migration_sql("restaurant_order_decision.sql"))
    db.execute(migration_sql("restaurant_order_decision.sql"))
    assert decide(db, number="NOPE-9") == {"result": "not_found"}
