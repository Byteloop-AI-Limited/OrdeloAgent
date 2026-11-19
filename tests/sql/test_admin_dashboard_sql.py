"""Admin dashboards (rest_admin, sys_admin) and overwatch identity on the isolated DB.

ordelo_datamodels/admin_dashboard/auth_sessions.sql (portal_access, *_dashboard_mint, admin_dashboard_activate / _touch,
rest_admin_session_actor, auth_sessions_revoke_phone) and the overwatch changes in restaurant_admin/admin_roster.sql
(is_overwatch, t_admin_link / t_admin_profile, revocation on relink / unlink). Every result value is covered.
Phones are in Ofcom's drama range 07700 900xxx (never a real person).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from .conftest import URI, fetch_one

pytestmark = pytest.mark.usefixtures("sql_env")

ADA, BOB, OPS, EVE = "447700900911", "447700900912", "447700900913", "447700900914"
T_ADA, T_BOB, T_OPS, T_NEW = 999000000911, 999000000912, 999000000913, 999000000919
H = {c: c * 64 for c in "abcdef"}  # sha256-shaped hashes
UA = "9" * 64


@pytest.fixture(autouse=True)
def clean(db):
    def wipe():
        db.execute("DELETE FROM public.auth_sessions WHERE principal_id LIKE '4477009009%'")
        db.execute("DELETE FROM public.restaurant_admin WHERE phone LIKE '4477009009%'")
        db.execute("DELETE FROM public.restaurant_master WHERE rest_ref IN ('ADA1', 'ADA2')")
        db.execute("DELETE FROM public.ordelo_config WHERE config_key = 'overwatch_list'")
    wipe()
    db.execute("INSERT INTO public.restaurant_master (rest_ref, rest_name, admins) VALUES"
               " ('ADA1', 'Ada One', %s), ('ADA2', 'Ada Two', %s)", ([ADA, "+44 7700 900912"], [ADA]))
    db.execute("INSERT INTO public.ordelo_config (config_key, config_value) VALUES ('overwatch_list', %s)",
               (f" +{OPS}, 447700900912 ,junk",))
    yield
    wipe()


def q(db, sql, *args):
    return fetch_one(db, sql, args)


def link(db, tuid, phone):
    return q(db, "SELECT public.t_admin_link(%s, %s, %s, 'u', 'F')", tuid, tuid, phone)


def mint_rest(db, ref="ADA1", tuid=T_ADA, phone=None, token=H["a"]):
    return q(db, "SELECT public.rest_admin_dashboard_mint(%s, %s, %s, %s)", tuid, phone, ref, token)


def mint_sys(db, tuid=None, phone=None, token=H["b"]):
    return q(db, "SELECT public.sys_admin_dashboard_mint(%s, %s, %s)", tuid, phone, token)


def activate(db, role, token, cookie, ip="203.0.113.7"):
    return q(db, "SELECT public.admin_dashboard_activate(%s, %s, %s, %s, %s)", role, token, cookie, UA, ip)


def touch(db, role, cookie, ua=UA):
    return q(db, "SELECT public.admin_dashboard_touch(%s, %s, %s)", role, cookie, ua)


# ---- is_overwatch ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("phone, expected", [(OPS, True), ("+44 7700 900913", True), (BOB, True), (ADA, False),
                                              ("junk", False), (None, False), ("", False)])
def test_is_overwatch_normalises_list_entries_and_input(db, phone, expected):
    assert q(db, "SELECT public.is_overwatch(%s)", phone) is expected


def test_no_overwatch_row_means_nobody(db):
    db.execute("DELETE FROM public.ordelo_config WHERE config_key = 'overwatch_list'")
    assert q(db, "SELECT public.is_overwatch(%s)", OPS) is False


# ---- t_admin_link / t_admin_profile with overwatch -------------------------------------------------------------------
def test_overwatch_only_phone_links_with_no_restaurants(db):
    r = link(db, T_OPS, OPS)
    assert r["result"] == "linked" and r["restaurants"] == [] and r["sys_admin"] is True
    p = q(db, "SELECT public.t_admin_profile(%s)", T_OPS)
    assert p["result"] == "ops_only" and p["sys_admin"] is True and p["restaurants"] == []


def test_overwatch_only_record_gets_no_restaurant_destinations(db):
    link(db, T_OPS, OPS)
    assert db.execute("SELECT count(*) FROM public.admin_roster WHERE phone = %s", (OPS,)).fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM public.admin_recipients('ADA1', 'telegram') WHERE phone = %s",
                      (OPS,)).fetchone()[0] == 0


def test_phone_on_neither_list_is_still_refused(db):
    assert link(db, T_NEW, EVE) == {"result": "not_on_roster"}


def test_dual_role_is_ok_with_sys_admin(db):
    r = link(db, T_BOB, BOB)
    assert r["result"] == "linked" and r["sys_admin"] is True and [x["rest_ref"] for x in r["restaurants"]] == ["ADA1"]
    assert q(db, "SELECT public.t_admin_profile(%s)", T_BOB)["result"] == "ok"


def test_ordinary_admin_is_not_sys_admin(db):
    assert link(db, T_ADA, ADA)["sys_admin"] is False
    assert q(db, "SELECT public.t_admin_profile(%s)", T_ADA)["sys_admin"] is False


def test_removed_from_overwatch_becomes_not_on_roster(db):
    link(db, T_OPS, OPS)
    db.execute("UPDATE public.ordelo_config SET config_value = '447700900912' WHERE config_key = 'overwatch_list'")
    p = q(db, "SELECT public.t_admin_profile(%s)", T_OPS)
    assert p["result"] == "not_on_roster" and p["sys_admin"] is False


# ---- portal_access --------------------------------------------------------------------------------------------------
def test_portal_access_by_tuid_and_by_phone(db):
    link(db, T_ADA, ADA)
    by_tuid = q(db, "SELECT public.portal_access(%s, NULL)", T_ADA)
    assert by_tuid == {"result": "ok", "phone": ADA, "sys_admin": False,
                       "restaurants": [{"rest_ref": "ADA1", "rest_name": "Ada One"},
                                       {"rest_ref": "ADA2", "rest_name": "Ada Two"}]}
    assert q(db, "SELECT public.portal_access(NULL, %s)", "+" + ADA) == by_tuid


def test_portal_access_unlinked_tuid_and_stranger_phone(db):
    assert q(db, "SELECT public.portal_access(%s, NULL)", T_NEW) == {"result": "not_linked"}
    out = q(db, "SELECT public.portal_access(NULL, %s)", EVE)
    assert out["result"] == "ok" and out["restaurants"] == [] and out["sys_admin"] is False


def test_portal_access_needs_exactly_one_actor(db):
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        q(db, "SELECT public.portal_access(%s, %s)", T_ADA, ADA)
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        q(db, "SELECT public.portal_access(NULL, NULL)")


# ---- mints ----------------------------------------------------------------------------------------------------------
def test_rest_admin_mint_every_result(db):
    link(db, T_ADA, ADA)
    assert mint_rest(db) == {"result": "ok"}
    row = db.execute("SELECT role, principal_id, scope_ref, wa_number, expires_at - created_at FROM public.auth_sessions"
                     " WHERE token_hash = %s", (H["a"],)).fetchone()
    assert row[:4] == ("rest_admin", ADA, "ADA1", ADA) and row[4].total_seconds() == 1800
    assert mint_rest(db, ref="ada2", token=H["c"]) == {"result": "ok"}  # rest_ref case-folded
    assert mint_rest(db, ref="ZZZZ", token=H["d"]) == {"result": "not_allowed"}
    assert mint_rest(db, tuid=T_NEW, token=H["e"]) == {"result": "not_linked"}
    assert mint_rest(db, tuid=None, phone=BOB, token=H["f"]) == {"result": "ok"}  # WhatsApp actor


def test_mint_rejects_a_malformed_hash(db):
    link(db, T_ADA, ADA)
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        mint_rest(db, token="not-a-hash")


def test_sys_admin_mint_every_result(db):
    link(db, T_OPS, OPS)
    link(db, T_ADA, ADA)
    assert mint_sys(db, tuid=T_OPS) == {"result": "ok"}
    assert mint_sys(db, tuid=T_ADA, token=H["c"]) == {"result": "not_allowed"}
    assert mint_sys(db, tuid=T_NEW, token=H["d"]) == {"result": "not_linked"}
    assert mint_sys(db, phone="+" + BOB, token=H["e"]) == {"result": "ok"}  # WhatsApp actor, formatted


# ---- activation and touch -------------------------------------------------------------------------------------------
def test_activation_is_single_use_and_touch_returns_the_session(db):
    link(db, T_ADA, ADA)
    mint_rest(db)
    out = activate(db, "rest_admin", H["a"], H["c"])
    assert out["result"] == "ok"
    assert activate(db, "rest_admin", H["a"], H["d"]) == {"result": "invalid", "reason": "not_found"}
    t = touch(db, "rest_admin", H["c"])
    assert t["result"] == "ok" and t["principal_id"] == ADA and t["scope_ref"] == "ADA1" and t["session_id"] == out["session_id"]


def test_activation_is_role_bound(db):
    link(db, T_ADA, ADA)
    mint_rest(db)
    assert activate(db, "sys_admin", H["a"], H["c"])["reason"] == "not_found"
    assert activate(db, "rider", H["a"], H["c"])["reason"] == "not_found"


def test_activation_reasons(db):
    link(db, T_ADA, ADA)
    mint_rest(db)
    db.execute("UPDATE public.auth_sessions SET expires_at = now() - interval '1 second' WHERE token_hash = %s", (H["a"],))
    assert activate(db, "rest_admin", H["a"], H["c"])["reason"] == "expired"
    mint_rest(db, token=H["b"])
    db.execute("UPDATE public.auth_sessions SET revoked = true WHERE token_hash = %s", (H["b"],))
    assert activate(db, "rest_admin", H["b"], H["c"])["reason"] == "revoked"


def test_removed_admin_cannot_activate_or_keep_a_session(db):
    link(db, T_ADA, ADA)
    mint_rest(db)
    mint_rest(db, token=H["b"])
    activate(db, "rest_admin", H["a"], H["c"])
    db.execute("UPDATE public.restaurant_master SET admins = '{}' WHERE rest_ref = 'ADA1'")
    assert activate(db, "rest_admin", H["b"], H["d"])["reason"] == "not_authorised"
    assert touch(db, "rest_admin", H["c"])["reason"] == "not_authorised"
    assert touch(db, "rest_admin", H["c"])["reason"] == "revoked"  # the failed touch revoked it


def test_removed_from_overwatch_loses_the_sys_admin_session(db):
    link(db, T_OPS, OPS)
    mint_sys(db, tuid=T_OPS)
    assert activate(db, "sys_admin", H["b"], H["c"])["result"] == "ok"
    assert touch(db, "sys_admin", H["c"])["result"] == "ok"
    db.execute("UPDATE public.ordelo_config SET config_value = '447700900912' WHERE config_key = 'overwatch_list'")
    assert touch(db, "sys_admin", H["c"])["reason"] == "not_authorised"


def test_touch_reasons(db):
    link(db, T_ADA, ADA)
    mint_rest(db)
    activate(db, "rest_admin", H["a"], H["c"])
    assert touch(db, "rest_admin", H["c"], ua="8" * 64)["reason"] == "ua_mismatch"
    assert touch(db, "rest_admin", H["d"])["reason"] == "no_session"
    assert touch(db, "sys_admin", H["c"])["reason"] == "no_session"
    db.execute("UPDATE public.auth_sessions SET last_seen_at = now() - interval '61 minutes' WHERE cookie_hash = %s", (H["c"],))
    assert touch(db, "rest_admin", H["c"])["reason"] == "idle"
    db.execute("UPDATE public.auth_sessions SET last_seen_at = now(), hard_expires_at = now() WHERE cookie_hash = %s", (H["c"],))
    assert touch(db, "rest_admin", H["c"])["reason"] == "hard_cap"


def test_touch_moves_last_seen_but_not_the_hard_cap(db):
    link(db, T_ADA, ADA)
    mint_rest(db)
    activate(db, "rest_admin", H["a"], H["c"])
    db.execute("UPDATE public.auth_sessions SET last_seen_at = now() - interval '10 minutes' WHERE cookie_hash = %s", (H["c"],))
    before = db.execute("SELECT last_seen_at, hard_expires_at FROM public.auth_sessions WHERE cookie_hash = %s", (H["c"],)).fetchone()
    touch(db, "rest_admin", H["c"])
    after = db.execute("SELECT last_seen_at, hard_expires_at FROM public.auth_sessions WHERE cookie_hash = %s", (H["c"],)).fetchone()
    assert after[0] > before[0] and after[1] == before[1]


def test_concurrent_activation_gives_exactly_one_cookie(db):
    link(db, T_ADA, ADA)
    mint_rest(db)

    def go(cookie):
        with psycopg.connect(URI, autocommit=True) as c:
            return c.execute("SELECT public.admin_dashboard_activate('rest_admin', %s, %s, %s, NULL)",
                             (H["a"], cookie, UA)).fetchone()[0]["result"]

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(go, [H["c"], H["d"], H["e"], H["f"]]))
    assert results.count("ok") == 1


# ---- revocation on relink / unlink ------------------------------------------------------------------------------------
def _live_rows(db, phone):
    return db.execute("SELECT count(*) FROM public.auth_sessions WHERE principal_id = %s AND NOT revoked", (phone,)).fetchone()[0]


def test_relink_to_another_account_revokes_sessions_and_unused_links(db):
    link(db, T_BOB, BOB)
    mint_rest(db, tuid=T_BOB, token=H["a"])
    activate(db, "rest_admin", H["a"], H["c"])
    mint_rest(db, tuid=T_BOB, token=H["b"])         # unused link
    mint_sys(db, tuid=T_BOB, token=H["d"])          # unused sys link
    link(db, T_ADA, ADA)
    mint_rest(db, tuid=T_ADA, token=H["e"])         # another phone: untouched
    assert _live_rows(db, BOB) == 3
    assert link(db, T_NEW, BOB)["result"] == "relinked"
    assert _live_rows(db, BOB) == 0 and _live_rows(db, ADA) == 1
    assert touch(db, "rest_admin", H["c"])["reason"] == "revoked"
    assert activate(db, "rest_admin", H["b"], H["f"])["reason"] == "revoked"
    assert mint_rest(db, tuid=T_NEW, token=H["f"]) == {"result": "ok"}  # the new account can mint again


def test_same_account_again_keeps_sessions(db):
    link(db, T_ADA, ADA)
    mint_rest(db)
    activate(db, "rest_admin", H["a"], H["c"])
    assert link(db, T_ADA, ADA)["result"] == "already_linked"
    assert touch(db, "rest_admin", H["c"])["result"] == "ok"


def test_unlink_revokes_sessions(db):
    link(db, T_ADA, ADA)
    mint_rest(db)
    activate(db, "rest_admin", H["a"], H["c"])
    assert q(db, "SELECT public.admin_unlink_telegram(%s, 'test')", ADA) == {"result": "ok"}
    assert touch(db, "rest_admin", H["c"])["reason"] == "revoked"


def test_rider_sessions_are_never_revoked_by_admin_relink(db):
    db.execute("INSERT INTO public.auth_sessions (role, principal_id, wa_number, token_hash, expires_at)"
               " VALUES ('rider', %s, %s, %s, now() + interval '30 minutes')", (BOB, BOB, H["f"]))
    link(db, T_BOB, BOB)
    link(db, T_NEW, BOB)
    assert db.execute("SELECT revoked FROM public.auth_sessions WHERE role = 'rider' AND principal_id = %s",
                      (BOB,)).fetchone()[0] is False


# ---- rest_admin_session_actor ---------------------------------------------------------------------------------------
def test_session_actor_returns_phone_and_restaurant_or_raises(db):
    link(db, T_ADA, ADA)
    mint_rest(db)
    sid = activate(db, "rest_admin", H["a"], H["c"])["session_id"]
    assert db.execute("SELECT phone, rest_ref FROM public.rest_admin_session_actor(%s)", (sid,)).fetchone() == (ADA, "ADA1")
    db.execute("UPDATE public.restaurant_master SET admins = '{}' WHERE rest_ref = 'ADA1'")
    with pytest.raises(psycopg.errors.InvalidAuthorizationSpecification):
        db.execute("SELECT * FROM public.rest_admin_session_actor(%s)", (sid,))
    with pytest.raises(psycopg.errors.InvalidAuthorizationSpecification):
        db.execute("SELECT * FROM public.rest_admin_session_actor('00000000-0000-0000-0000-000000000000')")


# ---- grants -----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("fn", ["is_overwatch(text)", "portal_access(bigint,text)",
                                "rest_admin_dashboard_mint(bigint,text,text,text)", "sys_admin_dashboard_mint(bigint,text,text)",
                                "admin_dashboard_activate(text,text,text,text,text)", "admin_dashboard_touch(text,text,text)",
                                "rest_admin_session_actor(uuid)", "auth_sessions_revoke_phone(text,text)"])
def test_service_role_only(db, fn):
    for role in ("anon", "authenticated"):
        assert q(db, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", role, "public." + fn) is False
    assert q(db, "SELECT has_function_privilege('service_role', %s, 'EXECUTE')", "public." + fn) is True
