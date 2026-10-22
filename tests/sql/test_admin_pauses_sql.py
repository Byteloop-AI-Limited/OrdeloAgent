"""Restaurant-admin pauses (phase R6) on the isolated DB: availability/pauses.sql (the last-admin guard), telegram/t_admin_pauses.sql
and t_alert_destinations() in telegram/t_order_alerts.sql (used by new cards, receipts and notices).

Proves: a restaurant can never be left with no unpaused admin (D52), including two admins pausing at the same moment; a
paused admin gets no NEW card, receipt or notice but keeps seeing and tapping what is already in the chat; the pause ends
by the clock with no sweep; the t_admin_* functions find the restaurants and the phone from the Telegram user alone (D14);
and the grants. Phones are in Ofcom's drama range 07700 900xxx.
"""

from __future__ import annotations

import threading

import psycopg
import pytest

from .conftest import _connect, fetch_one

pytestmark = pytest.mark.usefixtures("sql_env")

BOT = "rest_admin"
ORDER = "ELAS-PAUS-1"
ADA, BOB, EVE = "447700900801", "447700900802", "447700900803"


@pytest.fixture(autouse=True)
def clean(db):
    def wipe():
        db.execute("TRUNCATE public.delivery_summary, public.t_invites, public.restaurant_master, public.t_order_alerts, "
                   "public.t_sent_messages, public.food_order, public.order_item, public.http_calls CASCADE")
        db.execute("DELETE FROM public.pauses WHERE principal LIKE '4477009008%'")
        db.execute("UPDATE public.http_stub_status SET status = 200")
    wipe()
    db.execute("INSERT INTO public.ordelo_config (config_key, config_value) VALUES ('PAUSE_DURATIONS_REST_ADMIN', '6h,1d,3d'),"
               " ('TGRAM_ORDER_ALERT_OFFSETS_SECS', '0,15,30,45')"
               " ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value")
    db.execute("INSERT INTO public.restaurant_master (rest_ref, rest_name, admins) VALUES ('ELAS', 'Elas Kitchen', %s),"
               " ('WREN', 'Wren', %s)", ([ADA, "+44 7700 900802"], [ADA]))
    yield
    wipe()


def link(db, phone=ADA, uid=111, rest="ELAS", status="claimed"):
    db.execute("INSERT INTO public.t_invites (rest_ref, phone_number, status, claimed_at, telegram_user_id, telegram_chat_id,"
               " telegram_first_name) VALUES (%s, %s, %s, now(), %s, %s, 'X')", (rest, phone, status, uid, uid))


def start(db, who, rest="ELAS", dur="6h"):
    return fetch_one(db, "SELECT public.pause_start('rest_admin', %s, %s, %s, 'telegram', 'test')", (who, rest, dur))["result"]


def end(db, who, rest="ELAS"):
    return fetch_one(db, "SELECT public.pause_end('rest_admin', %s, %s, 'resumed')", (who, rest))["result"]


def dests(db, fn="t_alert_destinations", rest="ELAS"):
    return sorted(r[0] for r in db.execute(f"SELECT tcid FROM public.{fn}(%s, %s)", (BOT, rest)).fetchall())


def order(db, number=ORDER):
    db.execute("INSERT INTO public.delivery_summary (order_number) VALUES (%s)", (number,))
    db.execute("INSERT INTO public.food_order (order_id, order_number, total_price) VALUES (%s, %s, 9)", (number, number))


# ---- the last-admin guard (D52) ------------------------------------------------------------------------------------
def test_one_admin_may_pause_while_another_stays_on(db):
    assert start(db, ADA) == "paused"
    assert start(db, BOB) == "not_allowed"  # Ada is paused: Bob is the last one getting alerts
    assert start(db, ADA, dur="1d") == "extended"  # Ada extending is fine: Bob is still on
    assert end(db, ADA) == "resumed"
    assert start(db, BOB) == "paused"  # admins compared by digits ('+44 7700 900802')


def test_a_sole_admin_can_never_pause_and_strangers_are_refused(db):
    assert start(db, ADA, rest="WREN") == "not_allowed"
    assert start(db, EVE) == "not_admin"
    assert start(db, ADA, rest="NOPE") == "not_admin"
    assert start(db, ADA, dur="2w") == "bad_duration"


def test_an_expired_pause_no_longer_blocks_the_other_admin(db):
    start(db, ADA)
    db.execute("UPDATE public.pauses SET starts_at = now() - interval '7 hours', ends_at = now() - interval '1 minute'"
               " WHERE principal = %s", (ADA,))
    assert start(db, BOB) == "paused"


def test_two_admins_pausing_at_the_same_moment_cannot_both_pass():
    """Ada's pause holds the restaurant's advisory lock until it commits; Bob's waits, then sees Ada paused."""
    a, b = _connect(autocommit=False), _connect(autocommit=False)
    results = {}
    try:
        results["ada"] = a.execute("SELECT public.pause_start('rest_admin', %s, 'ELAS', '6h', 'telegram', 'a')", (ADA,)).fetchone()[0]

        def bob():
            results["bob"] = b.execute("SELECT public.pause_start('rest_admin', %s, 'ELAS', '6h', 'telegram', 'b')", (BOB,)).fetchone()[0]
            b.commit()

        t = threading.Thread(target=bob)
        t.start()
        t.join(1.0)
        assert t.is_alive(), "Bob's pause should wait for Ada's transaction"
        a.commit()
        t.join(10)
    finally:
        a.close()
        b.close()
    assert results["ada"]["result"] == "paused" and results["bob"]["result"] == "not_allowed"


# ---- who gets NEW alerts (t_alert_destinations) and who keeps access (t_order_card_destinations) ---------------------
def test_paused_admin_gets_no_new_alerts_but_keeps_access(db):
    link(db, ADA, 111)
    link(db, BOB, 222)
    start(db, ADA)
    assert dests(db) == [222]
    assert dests(db, "t_order_card_destinations") == [111, 222]  # may still see and tap
    order(db)
    snap = fetch_one(db, "SELECT public.t_order_card_snapshot(%s, %s, 'delivery')", (BOT, ORDER))
    assert [d["tcid"] for d in snap["destinations"]] == [222]
    assert [r[0] for r in db.execute("SELECT tcid FROM public.t_notice_targets(%s, 'ELAS', %s, 'card')", (BOT, ORDER))] == [222]
    receipt = fetch_one(db, "SELECT public.t_receipt_snapshot(%s, %s, 'delivery', NULL)", (BOT, ORDER))
    assert [d["tcid"] for d in receipt["destinations"]] == [222]
    # A card Ada already has is not treated as revoked: the refresh keeps it (authorised), it is never deleted for the pause.
    db.execute("INSERT INTO public.t_sent_messages (bot_key, tcid, message_id, tuid, subject_type, subject_ref, order_type, kind,"
               " rest_ref, card_status) VALUES (%s, 111, 5, 111, 'order', %s, 'delivery', 'order_card', 'ELAS', 'accepted')", (BOT, ORDER))
    stale = db.execute("SELECT authorised FROM public.t_order_cards_stale(%s, %s, 'delivery')", (BOT, ORDER)).fetchall()
    assert stale == [(True,)]


def test_the_pause_ends_by_the_clock_without_any_sweep(db):
    link(db, ADA, 111)
    link(db, BOB, 222)
    start(db, ADA)
    db.execute("UPDATE public.pauses SET starts_at = now() - interval '7 hours', ends_at = now() - interval '1 second'"
               " WHERE principal = %s", (ADA,))
    assert dests(db) == [111, 222]


def test_order_alert_sweep_seeds_nothing_when_every_linked_admin_is_paused(db):
    link(db, ADA, 111)  # Bob is an admin on WhatsApp only, so Ada may pause
    start(db, ADA)
    order(db)
    assert fetch_one(db, "SELECT public.job_t_order_alerts()") is True
    assert fetch_one(db, "SELECT count(*) FROM public.t_order_alerts") == 0
    end(db, ADA)
    fetch_one(db, "SELECT public.job_t_order_alerts()")
    assert fetch_one(db, "SELECT count(*) FROM public.t_order_alerts") == 4


# ---- t_admin_* (the restaurant bot's /off and /on) ----------------------------------------------------------------
def admin(db, fn, tuid=111, *extra):
    args = ", ".join(["%s"] * (2 + len(extra)))
    return fetch_one(db, f"SELECT public.{fn}({args})", (BOT, tuid, *extra))


def test_admin_pause_covers_every_linked_restaurant_with_one_result_each(db):
    link(db, ADA, 111, "ELAS")
    link(db, ADA, 111, "WREN")
    out = admin(db, "t_admin_pause", 111, "1d")
    assert out["result"] == "ok"
    rows = {r["rest_ref"]: r for r in out["restaurants"]}
    assert rows["ELAS"]["result"] == "paused" and rows["ELAS"]["ends_at"] and rows["ELAS"]["rest_name"] == "Elas Kitchen"
    assert rows["WREN"]["result"] == "not_allowed" and rows["WREN"]["ends_at"] is None  # Ada is Wren's only admin
    status = admin(db, "t_admin_pause_status", 111)
    assert status["options"] == ["6h", "1d", "3d"]
    assert [(r["rest_ref"], r["paused"]) for r in status["restaurants"]] == [("ELAS", True), ("WREN", False)]
    back = admin(db, "t_admin_resume", 111)
    assert [(r["rest_ref"], r["result"]) for r in back["restaurants"]] == [("ELAS", "resumed"), ("WREN", "not_paused")]


def test_admin_functions_refuse_people_who_are_not_linked_admins(db):
    link(db, EVE, 333)  # claimed, but Eve is not in restaurant_master.admins
    link(db, ADA, 444, status="revoked")
    for tuid in (333, 444, 999):
        assert admin(db, "t_admin_pause", tuid, "6h") == {"result": "not_linked"}
        assert admin(db, "t_admin_resume", tuid) == {"result": "not_linked"}
        assert admin(db, "t_admin_pause_status", tuid) == {"result": "not_linked"}


def test_admin_pause_with_an_unlisted_length_changes_nothing(db):
    link(db, ADA, 111)
    out = admin(db, "t_admin_pause", 111, "9d")
    assert [r["result"] for r in out["restaurants"]] == ["bad_duration"]
    assert fetch_one(db, "SELECT count(*) FROM public.pauses WHERE principal = %s", (ADA,)) == 0


def test_admin_pause_chats_are_that_admins_chats_for_that_restaurant(db):
    link(db, ADA, 111, "ELAS")
    link(db, BOB, 222, "ELAS")
    link(db, ADA, 111, "WREN")
    assert fetch_one(db, "SELECT public.t_admin_pause_chats(%s, %s, 'ELAS')", (BOT, ADA)) == [{"tcid": 111, "rest_name": "Elas Kitchen"}]
    assert fetch_one(db, "SELECT public.t_admin_pause_chats(%s, '+44 7700 900802', 'ELAS')", (BOT,)) == [{"tcid": 222, "rest_name": "Elas Kitchen"}]
    assert fetch_one(db, "SELECT public.t_admin_pause_chats(%s, %s, 'WREN')", (BOT, BOB)) == []


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_public_roles_cannot_call(db, role):
    db.execute(f"SET ROLE {role}")
    try:
        for sql in ("SELECT public.t_admin_pause('rest_admin', 1, '6h')", "SELECT public.t_admin_resume('rest_admin', 1)",
                    "SELECT public.t_admin_pause_status('rest_admin', 1)",
                    "SELECT public.t_admin_pause_chats('rest_admin', '447700900801', 'ELAS')",
                    "SELECT * FROM public.t_alert_destinations('rest_admin', 'ELAS')"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db.execute(sql)
    finally:
        db.execute("RESET ROLE")
