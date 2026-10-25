"""migrations/admin_roster_p1.sql on the isolated DB: its PRE-CHECK and VERIFY blocks run, and (the point of phase P1) the new
Telegram destination functions give EXACTLY what the old invite-only logic gave while no admin record exists.

OLD_* below are the pre-roster definitions (git show d486b43:ordelo_datamodels/telegram/t_order_alerts.sql and
restaurant_admin/restaurant_order_decision.sql), kept here as the oracle.
"""

from __future__ import annotations

import re

import pytest

from .conftest import MIGRATIONS

pytestmark = pytest.mark.usefixtures("sql_env")

MIGRATION = (MIGRATIONS / "admin_roster_p1.sql").read_text()
BOT = "rest_admin"

OLD_CARD_DESTINATIONS = """
    SELECT DISTINCT ON (i.telegram_chat_id) i.telegram_chat_id, i.telegram_user_id, i.phone_number, i.telegram_first_name
    FROM public.t_invites i JOIN public.restaurant_master rm ON rm.rest_ref = i.rest_ref
    WHERE i.bot_key = %(bot)s AND i.rest_ref = %(rest)s AND i.status = 'claimed' AND i.telegram_chat_id IS NOT NULL
      AND i.phone_number IN (SELECT regexp_replace(a, '\\D', '', 'g') FROM unnest(rm.admins) AS a)
    ORDER BY i.telegram_chat_id, i.claimed_at DESC NULLS LAST"""
OLD_ADMIN_PHONE = """
    SELECT i.phone_number FROM public.t_invites i JOIN public.restaurant_master rm ON rm.rest_ref = i.rest_ref
    WHERE i.bot_key = %(bot)s AND i.telegram_user_id = %(tuid)s AND i.rest_ref = %(rest)s AND i.status = 'claimed'
      AND i.phone_number IN (SELECT regexp_replace(a, '\\D', '', 'g') FROM unnest(rm.admins) AS a)
    ORDER BY i.claimed_at DESC NULLS LAST LIMIT 1"""
OLD_LABEL = """
    SELECT COALESCE((SELECT i.telegram_first_name FROM public.t_invites i WHERE i.phone_number = %(p)s AND i.status = 'claimed'
                      AND i.telegram_first_name IS NOT NULL ORDER BY i.claimed_at DESC LIMIT 1),
                    CASE WHEN coalesce(%(p)s, '') = '' THEN NULL ELSE '…' || RIGHT(%(p)s, 4) END)"""


def blocks(label: str) -> str:
    m = re.search(rf"-- {re.escape(label)}[^\n]*\n(.*?;)\n", MIGRATION, re.S)
    assert m, label
    return m.group(1)


@pytest.fixture(autouse=True)
def world(db):
    def wipe():
        db.execute("TRUNCATE public.restaurant_admin, public.t_invites, public.restaurant_master CASCADE")
    wipe()
    db.execute("INSERT INTO public.restaurant_master (rest_ref, rest_name, admins) VALUES"
               " ('ELAS', 'Elas', %s), ('WREN', 'Wren', %s), ('ODDS', 'Odds', %s)",
               (["+44 7700 900701", "447700900702", "447700900703"], ["447700900701"], ["12345", "", "447700900704"]))
    inv = [  # rest, phone, tuid, chat, name, status, claimed_at offset (minutes ago)
        ("ELAS", "447700900701", 1, 11, "Ada", "claimed", 30),
        ("ELAS", "447700900702", 2, 22, "Bob", "claimed", 20),
        ("ELAS", "447700900703", 3, 22, "Cal", "claimed", 10),     # two admins sharing one chat: one card
        ("ELAS", "447700900799", 9, 99, "Stranger", "claimed", 1),  # claimed, phone not on the list
        ("ELAS", "447700900702", 5, 55, "Revoked", "revoked", 3),
        ("WREN", "447700900701", 1, 11, "Ada", "claimed", 15),
        ("ODDS", "447700900704", 4, 44, "Dee", "claimed", 12),
    ]
    for rest, phone, tuid, chat, name, status, mins in inv:
        db.execute("INSERT INTO public.t_invites (rest_ref, phone_number, status, claimed_at, telegram_user_id, telegram_chat_id,"
                   " telegram_first_name) VALUES (%s, %s, %s, now() - make_interval(mins => %s), %s, %s, %s)",
                   (rest, phone, status, mins, tuid, chat, name))
    yield
    wipe()


def test_pre_check_1_lists_exactly_the_entries_the_roster_would_reject(db):
    assert db.execute(blocks("PRE-CHECK 1")).fetchall() == [("ODDS", "12345"), ("ODDS", "")]


def test_pre_check_3_lists_phones_on_more_than_one_restaurant(db):
    assert db.execute(blocks("PRE-CHECK 3")).fetchall() == [("447700900701", ["ELAS", "WREN"])]


def test_verify_counts_and_verify_2_equals_pre_check_2(db):
    functions, records, uses_roster = db.execute(blocks("VERIFY (after STEP 1)")).fetchone()
    assert (functions, records, uses_roster) == (9, 0, True)
    assert db.execute(blocks("VERIFY 2")).fetchall() == db.execute(blocks("PRE-CHECK 2")).fetchall()


@pytest.mark.parametrize("rest", ["ELAS", "WREN", "ODDS", "NONE"])
def test_card_destinations_equal_the_old_invite_logic_while_no_record_exists(db, rest):
    old = db.execute(OLD_CARD_DESTINATIONS, {"bot": BOT, "rest": rest}).fetchall()
    new = db.execute("SELECT tcid, tuid, phone, label FROM public.t_order_card_destinations(%s, %s) ORDER BY tcid", (BOT, rest)).fetchall()
    assert sorted(new) == sorted(old)


@pytest.mark.parametrize("rest", ["ELAS", "WREN", "ODDS"])
@pytest.mark.parametrize("tuid", [1, 2, 3, 4, 5, 9, 12345])
def test_admin_phone_equals_the_old_invite_logic_while_no_record_exists(db, rest, tuid):
    old = db.execute(OLD_ADMIN_PHONE, {"bot": BOT, "tuid": tuid, "rest": rest}).fetchone()
    new = db.execute("SELECT public.t_order_admin_phone(%s, %s, %s)", (BOT, tuid, rest)).fetchone()[0]
    assert new == (old[0] if old else None)


@pytest.mark.parametrize("phone", ["447700900701", "447700900702", "447700900799", "447700900888", "", None])
def test_label_equals_the_old_invite_logic_while_no_record_exists(db, phone):
    old = db.execute(OLD_LABEL, {"p": phone}).fetchone()[0]
    assert db.execute("SELECT public.restaurant_admin_label(%s)", (phone,)).fetchone()[0] == old


def test_alert_destinations_equal_card_destinations_while_nobody_is_paused_and_no_record_exists(db):
    for rest in ("ELAS", "WREN", "ODDS"):
        a = db.execute("SELECT tcid FROM public.t_alert_destinations(%s, %s) ORDER BY 1", (BOT, rest)).fetchall()
        b = db.execute("SELECT tcid FROM public.t_order_card_destinations(%s, %s) ORDER BY 1", (BOT, rest)).fetchall()
        assert a == b


def test_pause_status_for_an_invite_only_admin_matches_the_old_shape(db):
    out = db.execute("SELECT public.t_admin_pause_status(%s, 1)", (BOT,)).fetchone()[0]
    assert out["result"] == "ok" and [r["rest_ref"] for r in out["restaurants"]] == ["ELAS", "WREN"]
    assert db.execute("SELECT public.t_admin_pause_status(%s, 9)", (BOT,)).fetchone()[0] == {"result": "not_linked"}
