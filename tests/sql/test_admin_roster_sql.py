"""Admin roster SQL (ordelo_datamodels/restaurant_admin/admin_roster.sql) on the isolated DB.

Covers every result value of t_admin_link / t_admin_profile / admin_set_channels / admin_unlink_telegram, the roster view
(formatted numbers, rejected entries, a phone on two restaurants, list order), admin_recipients() per channel with pauses,
admin_roster_status(), the CHECK constraints and the service-role-only grants. Phones are in Ofcom's drama range
07700 900xxx (never a real person).
"""

from __future__ import annotations

import threading

import psycopg
import pytest

from .conftest import _connect, fetch_one

pytestmark = pytest.mark.usefixtures("sql_env")

ADA, BOB, EVE, CAL = "447700900901", "447700900902", "447700900903", "447700900904"
T_ADA, T_BOB, T_EVE = 999000000901, 999000000902, 999000000903


@pytest.fixture(autouse=True)
def clean(db):
    def wipe():
        db.execute("TRUNCATE public.restaurant_admin, public.t_invites, public.restaurant_master CASCADE")
        db.execute("DELETE FROM public.pauses WHERE principal LIKE '4477009009%'")
    wipe()
    db.execute("INSERT INTO public.restaurant_master (rest_ref, rest_name, admins) VALUES"
               " ('ELAS', 'Elas Kitchen', %s), ('WREN', 'Wren', %s), ('ODDS', 'Odds', %s)",
               (["+44 7700 900901", "447700900902"], ["447700900901"], ["12345", "", "447700900904"]))
    yield
    wipe()


def link(db, tuid=T_ADA, phone=ADA, tcid=None, username="ada", first="Ada"):
    return fetch_one(db, "SELECT public.t_admin_link(%s, %s, %s, %s, %s)", (tuid, tcid or tuid, phone, username, first))


def recipients(db, rest, channel):
    return [r[0] for r in db.execute("SELECT phone FROM public.admin_recipients(%s, %s)", (rest, channel)).fetchall()]


@pytest.mark.parametrize("raw, digits", [("+44 7700 900901", ADA), ("447700900901", ADA), ("(44) 7700-900901", ADA),
                                           ("12345", None), ("", None), (None, None), ("4477009009011234", None)])
def test_phone_rule_is_digits_only_eight_to_fifteen(db, raw, digits):
    assert fetch_one(db, "SELECT public.admin_phone_digits(%s)", (raw,)) == digits


# ---- the roster view -----------------------------------------------------------------------------------------------
def test_roster_has_one_row_per_restaurant_and_phone_in_list_order_and_skips_rejected_entries(db):
    rows = db.execute("SELECT rest_ref, phone, ord FROM public.admin_roster ORDER BY rest_ref, ord").fetchall()
    assert rows == [("ELAS", ADA, 1), ("ELAS", BOB, 2), ("ODDS", CAL, 3), ("WREN", ADA, 1)]


def test_a_phone_with_no_record_defaults_to_whatsapp(db):
    assert fetch_one(db, "SELECT channels FROM public.admin_roster WHERE rest_ref = 'ELAS' AND phone = %s", (ADA,)) == ["whatsapp"]


# ---- t_admin_link --------------------------------------------------------------------------------------------------
def test_first_link_creates_the_record_and_moves_the_admin_to_telegram_only(db):
    r = link(db)
    assert r["result"] == "linked" and r["phone"] == ADA and r["channels"] == ["telegram"]
    assert r["restaurants"] == [{"rest_ref": "ELAS", "rest_name": "Elas Kitchen"}, {"rest_ref": "WREN", "rest_name": "Wren"}]
    assert recipients(db, "ELAS", "telegram") == [ADA] and recipients(db, "ELAS", "whatsapp") == [BOB]


def test_formatted_phone_links_the_same_record(db):
    assert link(db, phone="+44 7700 900901")["phone"] == ADA


def test_same_account_again_refreshes_and_keeps_channels(db):
    link(db)
    db.execute("SELECT public.admin_set_channels(%s, ARRAY['whatsapp','telegram'], 'test')", (ADA,))
    r = link(db, tcid=777, first="Ada L")
    assert r["result"] == "already_linked" and r["channels"] == ["telegram", "whatsapp"]
    assert db.execute("SELECT tcid, t_first_name FROM public.restaurant_admin WHERE phone = %s", (ADA,)).fetchone() == (777, "Ada L")


def test_another_account_proving_the_phone_moves_the_link_and_reports_the_old_one(db):
    link(db)
    r = link(db, tuid=T_EVE, username="eve", first="Eve")
    assert r["result"] == "relinked" and r["previous_tuid"] == T_ADA and r["previous_username"] == "ada"
    assert fetch_one(db, "SELECT tuid FROM public.restaurant_admin WHERE phone = %s", (ADA,)) == T_EVE
    assert fetch_one(db, "SELECT public.admin_for_tuid(%s, 'ELAS')", (T_ADA,)) is None


def test_relink_keeps_a_channel_choice_made_in_between(db):
    link(db)
    db.execute("SELECT public.admin_set_channels(%s, ARRAY['whatsapp'], 'sys-admin')", (ADA,))
    assert link(db, tuid=T_EVE)["channels"] == ["whatsapp"]


def test_a_phone_on_no_list_is_refused_and_writes_nothing(db):
    assert link(db, phone="447700900999")["result"] == "not_on_roster"
    assert fetch_one(db, "SELECT count(*) FROM public.restaurant_admin") == 0


def test_one_telegram_account_cannot_take_two_phones(db):
    link(db)
    r = link(db, phone=BOB)
    assert r["result"] == "tuid_taken" and r["phone_last4"] == "0901"
    assert fetch_one(db, "SELECT count(*) FROM public.restaurant_admin") == 1


@pytest.mark.parametrize("phone", ["12345", "", None, "abc"])
def test_bad_numbers_are_refused(db, phone):
    assert link(db, phone=phone)["result"] == "bad_phone"


def test_missing_telegram_ids_are_refused(db):
    assert fetch_one(db, "SELECT public.t_admin_link(NULL, 1, %s, 'a', 'A')", (ADA,))["result"] == "bad_phone"


def test_a_rejected_list_entry_cannot_be_linked(db):
    assert link(db, phone="12345")["result"] == "bad_phone"


def test_two_accounts_linking_the_same_new_phone_at_once_leave_one_winner():
    results = []

    def go(tuid):
        with _connect() as c:
            results.append(fetch_one(c, "SELECT public.t_admin_link(%s, %s, %s, 'x', 'X')", (tuid, tuid, BOB))["result"])

    threads = [threading.Thread(target=go, args=(t,)) for t in (T_BOB, T_EVE)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) in (["linked", "relinked"],)
    with _connect() as c:
        assert fetch_one(c, "SELECT count(*) FROM public.restaurant_admin WHERE phone = %s", (BOB,)) == 1


# ---- t_admin_profile -----------------------------------------------------------------------------------------------
def test_profile_for_a_linked_unlinked_and_removed_admin(db):
    assert fetch_one(db, "SELECT public.t_admin_profile(%s)", (T_ADA,)) == {"result": "not_linked"}
    link(db)
    p = fetch_one(db, "SELECT public.t_admin_profile(%s)", (T_ADA,))
    assert p["result"] == "ok" and p["phone"] == ADA and p["channels"] == ["telegram"] and len(p["restaurants"]) == 2
    db.execute("UPDATE public.restaurant_master SET admins = '{}'")
    assert fetch_one(db, "SELECT public.t_admin_profile(%s)", (T_ADA,))["result"] == "not_on_roster"


def test_removing_the_phone_from_every_list_stops_authority_and_messages(db):
    link(db)
    db.execute("UPDATE public.restaurant_master SET admins = array_remove(admins, '447700900901') WHERE rest_ref = 'WREN'")
    db.execute("UPDATE public.restaurant_master SET admins = ARRAY['447700900902'] WHERE rest_ref = 'ELAS'")
    assert fetch_one(db, "SELECT public.admin_for_tuid(%s, 'ELAS')", (T_ADA,)) is None
    assert recipients(db, "ELAS", "telegram") == [] and recipients(db, "WREN", "telegram") == []


# ---- channels ------------------------------------------------------------------------------------------------------
def test_channel_choices_and_their_refusals(db):
    assert fetch_one(db, "SELECT public.admin_set_channels(%s, ARRAY['whatsapp'], 'x')", (ADA,))["result"] == "not_found"
    link(db)
    ok = fetch_one(db, "SELECT public.admin_set_channels(%s, ARRAY['whatsapp','telegram','whatsapp'], 'sys-admin')", (ADA,))
    assert ok == {"result": "ok", "channels": ["telegram", "whatsapp"]}
    assert recipients(db, "ELAS", "telegram") == [ADA] and recipients(db, "ELAS", "whatsapp") == [ADA, BOB]
    for bad in ("ARRAY[]::text[]", "ARRAY['sms']", "NULL"):
        assert fetch_one(db, f"SELECT public.admin_set_channels(%s, {bad}, 'x')", (ADA,))["result"] == "bad_channels"


def test_telegram_cannot_be_chosen_without_a_link(db):
    link(db)
    db.execute("SELECT public.admin_unlink_telegram(%s, 'x')", (ADA,))
    r = fetch_one(db, "SELECT public.admin_set_channels(%s, ARRAY['telegram'], 'x')", (ADA,))
    assert r["result"] == "not_linked" and r["channels"] == ["whatsapp"]


def test_unlink_goes_back_to_whatsapp_and_the_person_can_link_again(db):
    link(db)
    assert fetch_one(db, "SELECT public.admin_unlink_telegram(%s, 'operator')", (ADA,))["result"] == "ok"
    assert fetch_one(db, "SELECT public.admin_unlink_telegram(%s, 'operator')", (ADA,))["result"] == "not_linked"
    assert fetch_one(db, "SELECT public.admin_unlink_telegram(%s, 'operator')", (CAL,))["result"] == "not_found"
    assert recipients(db, "ELAS", "telegram") == [] and recipients(db, "ELAS", "whatsapp") == [ADA, BOB]
    assert link(db)["result"] == "linked"


def test_the_table_refuses_inconsistent_rows(db):
    for sql in ("INSERT INTO public.restaurant_admin (phone, channels) VALUES ('447700900901', ARRAY['telegram'])",
                "INSERT INTO public.restaurant_admin (phone, tuid) VALUES ('447700900901', 5)",
                "INSERT INTO public.restaurant_admin (phone, channels) VALUES ('447700900901', ARRAY[]::text[])",
                "INSERT INTO public.restaurant_admin (phone) VALUES ('+4477')"):
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(sql)


# ---- recipients, pauses and order ----------------------------------------------------------------------------------
def test_a_paused_admin_is_not_a_recipient_on_any_channel(db):
    link(db)
    db.execute("SELECT public.admin_set_channels(%s, ARRAY['whatsapp','telegram'], 'x')", (ADA,))
    assert fetch_one(db, "SELECT public.pause_start('rest_admin', %s, 'ELAS', '6h', 'telegram', 'test')", (ADA,))["result"] == "paused"
    assert recipients(db, "ELAS", "telegram") == [] and recipients(db, "ELAS", "whatsapp") == [BOB]
    assert recipients(db, "WREN", "telegram") == [ADA]  # the pause is per restaurant


def test_recipients_keep_the_admins_list_order(db):
    db.execute("UPDATE public.restaurant_master SET admins = ARRAY['447700900902', '+44 7700 900901'] WHERE rest_ref = 'ELAS'")
    assert recipients(db, "ELAS", "whatsapp") == [BOB, ADA]


def test_a_duplicate_entry_in_one_list_counts_once(db):
    db.execute("UPDATE public.restaurant_master SET admins = ARRAY['447700900901', '+44 7700 900901'] WHERE rest_ref = 'WREN'")
    assert recipients(db, "WREN", "whatsapp") == [ADA]


# ---- admin_roster_status -------------------------------------------------------------------------------------------
def test_status_lists_every_entry_including_rejected_ones_in_order(db):
    link(db)
    rows = fetch_one(db, "SELECT public.admin_roster_status('ODDS')")
    assert [(r["raw"], r["valid"]) for r in rows] == [("12345", False), ("", False), ("447700900904", True)]
    elas = fetch_one(db, "SELECT public.admin_roster_status('ELAS')")
    assert [(r["phone"], r["linked"], r["channels"]) for r in elas] == [(ADA, True, ["telegram"]), (BOB, False, ["whatsapp"])]
    assert fetch_one(db, "SELECT public.admin_roster_status('NONE')") == []


def test_status_flags_an_invite_only_admin_until_a_record_exists(db):
    db.execute("INSERT INTO public.t_invites (rest_ref, phone_number, status, claimed_at, telegram_user_id, telegram_chat_id,"
               " telegram_first_name) VALUES ('ELAS', %s, 'claimed', now(), 5, 5, 'Bob')", (BOB,))
    assert fetch_one(db, "SELECT public.admin_roster_status('ELAS')")[1]["legacy_invite"] is True
    link(db, tuid=T_BOB, phone=BOB, first="Bob")
    assert fetch_one(db, "SELECT public.admin_roster_status('ELAS')")[1]["legacy_invite"] is False


# ---- grants --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("fn", ["admin_recipients(text,text)", "admin_for_tuid(bigint,text)",
                                "t_admin_link(bigint,bigint,text,text,text)", "t_admin_profile(bigint)",
                                "admin_set_channels(text,text[],text)", "admin_unlink_telegram(text,text)",
                                "admin_roster_status(text)", "t_admin_restaurants(text,bigint)"])
def test_functions_are_service_role_only(db, fn):
    for role in ("anon", "authenticated"):
        assert fetch_one(db, "SELECT has_function_privilege(%s, %s::regprocedure, 'EXECUTE')", (role, f"public.{fn}")) is False


def test_table_and_view_are_closed_to_anon_and_authenticated(db):
    for role in ("anon", "authenticated"):
        for rel in ("restaurant_admin", "admin_roster"):
            assert fetch_one(db, "SELECT has_table_privilege(%s, %s, 'SELECT')", (role, f"public.{rel}")) is False
    assert fetch_one(db, "SELECT relrowsecurity FROM pg_class WHERE oid = 'public.restaurant_admin'::regclass") is True
