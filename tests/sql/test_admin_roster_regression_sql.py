"""Regression net for the roster transition (plans/restaurant-admin-roster-onboarding-plan.md, P1).

While an admin has NO admin record, every t_* destination function must give exactly what the claimed invite gave before the
roster existed; once a record exists it alone governs that phone (the invite stops mattering). Phones: Ofcom drama range.
"""

from __future__ import annotations

import pytest

from .conftest import fetch_one

pytestmark = pytest.mark.usefixtures("sql_env")

BOT = "rest_admin"
ADA, BOB = "447700900911", "447700900912"


@pytest.fixture(autouse=True)
def clean(db):
    def wipe():
        db.execute("TRUNCATE public.restaurant_admin, public.t_invites, public.restaurant_master CASCADE")
        db.execute("DELETE FROM public.pauses WHERE principal LIKE '4477009009%'")
    wipe()
    db.execute("INSERT INTO public.restaurant_master (rest_ref, rest_name, admins) VALUES ('ELAS', 'Elas Kitchen', %s),"
               " ('WREN', 'Wren', %s)", (["+44 7700 900911", BOB], [ADA]))
    yield
    wipe()


def invite(db, phone, uid, rest="ELAS", name="Inv"):
    db.execute("INSERT INTO public.t_invites (rest_ref, phone_number, status, claimed_at, telegram_user_id, telegram_chat_id,"
               " telegram_first_name) VALUES (%s, %s, 'claimed', now(), %s, %s, %s)", (rest, phone, uid, uid, name))


def dests(db, fn, rest="ELAS"):
    return db.execute(f"SELECT tcid, tuid, phone, label FROM public.{fn}(%s, %s) ORDER BY tcid", (BOT, rest)).fetchall()


def test_invite_only_admin_behaves_exactly_as_before(db):
    invite(db, ADA, 111, name="Ada")
    assert dests(db, "t_order_card_destinations") == [(111, 111, ADA, "Ada")]
    assert dests(db, "t_alert_destinations") == dests(db, "t_order_card_destinations")
    assert fetch_one(db, "SELECT public.t_order_admin_phone(%s, 111, 'ELAS')", (BOT,)) == ADA
    assert fetch_one(db, "SELECT public.restaurant_admin_label(%s)", (ADA,)) == "Ada"
    assert fetch_one(db, "SELECT public.t_admin_pause_status(%s, 111)", (BOT,))["restaurants"][0]["rest_ref"] == "ELAS"


def test_an_invite_for_a_phone_not_on_the_list_still_gives_nothing(db):
    invite(db, "447700900999", 222)
    assert dests(db, "t_order_card_destinations") == []
    assert fetch_one(db, "SELECT public.t_order_admin_phone(%s, 222, 'ELAS')", (BOT,)) is None
    assert fetch_one(db, "SELECT public.t_admin_pause_status(%s, 222)", (BOT,)) == {"result": "not_linked"}


def test_a_revoked_invite_gives_nothing(db):
    invite(db, ADA, 111)
    db.execute("UPDATE public.t_invites SET status = 'revoked'")
    assert dests(db, "t_order_card_destinations") == []


def test_the_record_governs_once_it_exists_and_the_old_invite_stops_mattering(db):
    invite(db, ADA, 111, name="Old")
    fetch_one(db, "SELECT public.t_admin_link(333, 333, %s, 'ada', 'New')", (ADA,))
    assert dests(db, "t_order_card_destinations") == [(333, 333, ADA, "New")]
    assert dests(db, "t_alert_destinations") == [(333, 333, ADA, "New")]
    assert fetch_one(db, "SELECT public.t_order_admin_phone(%s, 111, 'ELAS')", (BOT,)) is None
    assert fetch_one(db, "SELECT public.t_order_admin_phone(%s, 333, 'ELAS')", (BOT,)) == ADA
    assert fetch_one(db, "SELECT public.restaurant_admin_label(%s)", (ADA,)) == "New"


def test_whatsapp_only_record_keeps_card_access_but_gets_no_new_telegram_alerts(db):
    fetch_one(db, "SELECT public.t_admin_link(333, 333, %s, 'ada', 'Ada')", (ADA,))
    db.execute("SELECT public.admin_set_channels(%s, ARRAY['whatsapp'], 'x')", (ADA,))
    assert len(dests(db, "t_order_card_destinations")) == 1  # can still see and tap existing cards
    assert dests(db, "t_alert_destinations") == []            # but new cards, receipts and notices skip them


def test_a_linked_admin_on_two_restaurants_is_found_on_both_and_pauses_both(db):
    fetch_one(db, "SELECT public.t_admin_link(333, 333, %s, 'ada', 'Ada')", (ADA,))
    assert [r[0] for r in db.execute("SELECT rest_ref FROM public.t_admin_restaurants(%s, 333) ORDER BY 1", (BOT,))] == ["ELAS", "WREN"]
    db.execute("INSERT INTO public.ordelo_config (config_key, config_value) VALUES ('PAUSE_DURATIONS_REST_ADMIN', '6h') ON CONFLICT (config_key) DO NOTHING")
    # ELAS has another unpaused admin (BOB, WhatsApp) so Ada may pause there; WREN has only Ada (last-admin guard).
    res = fetch_one(db, "SELECT public.t_admin_pause(%s, 333, '6h')", (BOT,))
    assert {r["rest_ref"]: r["result"] for r in res["restaurants"]} == {"ELAS": "paused", "WREN": "not_allowed"}
    assert dests(db, "t_alert_destinations", "ELAS") == []


def test_invite_and_record_for_different_people_do_not_leak_into_each_other(db):
    invite(db, BOB, 444, name="Bob")                       # Bob: invite only
    fetch_one(db, "SELECT public.t_admin_link(333, 333, %s, 'ada', 'Ada')", (ADA,))  # Ada: record
    assert [r[0] for r in dests(db, "t_alert_destinations")] == [333, 444]
