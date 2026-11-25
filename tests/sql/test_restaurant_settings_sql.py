"""Restaurant-dashboard settings on the isolated DB (ordelo_datamodels/restaurant_admin/restaurant_settings.sql).

Acceptance policy through the session-bound RPCs, the audit trail, the stale-edit guard, needs_defaults, inherit/reset,
the sys-admin change list and undo (ok / changed_since / already_reverted / not_found / not_revertible), and agreement of
restaurant_default_pickup_minutes() with the live order-creation lookup resolve_initial_restaurant_acceptance().
"""

from __future__ import annotations

import pytest

from .conftest import fetch_one

pytestmark = pytest.mark.usefixtures("sql_env")

ADA, BOB = "447700900931", "447700900932"
H = {c: c * 64 for c in "abcdef"}
UA = "9" * 64
KEYS = ("SET1_DEFAULT_DELIVERY_PICKUP_TIME", "SET1_DEFAULT_COLLECTION_PICKUP_TIME",
        "DEFAULT_DELIVERY_PICKUP_TIME", "DEFAULT_COLLECTION_PICKUP_TIME")


@pytest.fixture(autouse=True)
def clean(db):
    def wipe():
        db.execute("DELETE FROM public.restaurant_settings_audit WHERE rest_ref IN ('SET1', 'SET2')")
        db.execute("DELETE FROM public.auth_sessions WHERE principal_id LIKE '4477009009%'")
        db.execute("DELETE FROM public.restaurant_admin WHERE phone LIKE '4477009009%'")
        db.execute("DELETE FROM public.restaurant_master WHERE rest_ref IN ('SET1', 'SET2')")
        db.execute("DELETE FROM public.ordelo_config WHERE config_key = ANY(%s)", (list(KEYS),))
    wipe()
    db.execute("INSERT INTO public.restaurant_master (rest_ref, rest_name, admins) VALUES ('SET1', 'Set One', %s),"
               " ('SET2', 'Set Two', %s)", ([ADA], [BOB]))
    db.execute("INSERT INTO public.ordelo_config (config_key, config_value) VALUES"
               " ('DEFAULT_DELIVERY_PICKUP_TIME', '30'), ('DEFAULT_COLLECTION_PICKUP_TIME', '25')")
    yield
    wipe()


def session(db, phone=ADA, ref="SET1", token="a", cookie="c"):
    db.execute("INSERT INTO public.auth_sessions (role, principal_id, scope_ref, wa_number, token_hash, expires_at)"
               " VALUES ('rest_admin', %s, %s, %s, %s, now() + interval '30 minutes')", (phone, ref, phone, H[token]))
    return fetch_one(db, "SELECT public.admin_dashboard_activate('rest_admin', %s, %s, %s, NULL)", (H[token], H[cookie], UA))["session_id"]


def get(db, sid):
    return fetch_one(db, "SELECT public.rest_admin_acceptance_get(%s)", (sid,))


def put(db, sid, auto, dmin, cmin, version):
    return fetch_one(db, "SELECT public.rest_admin_acceptance_set(%s, %s, %s, %s, %s)", (sid, auto, dmin, cmin, version))


def audit(db, ref="SET1"):
    return db.execute("SELECT setting, old_value, new_value, by_who, via FROM public.restaurant_settings_audit"
                      " WHERE rest_ref = %s ORDER BY id", (ref,)).fetchall()


def test_get_reports_inherited_defaults(db):
    s = get(db, session(db))
    assert s["result"] == "ok" and s["auto_accept"] is False
    assert s["delivery"] == {"minutes": 30, "inherited": True, "own": None}
    assert s["collection"] == {"minutes": 25, "inherited": True, "own": None}


def test_set_writes_values_and_one_audit_row_per_changed_setting(db):
    sid = session(db)
    v = get(db, sid)["version"]
    out = put(db, sid, True, 20, None, v)
    assert out["result"] == "ok" and out["state"]["auto_accept"] is True
    assert out["state"]["delivery"] == {"minutes": 20, "inherited": False, "own": 20}
    assert fetch_one(db, "SELECT config_value FROM public.ordelo_config WHERE config_key = 'SET1_DEFAULT_DELIVERY_PICKUP_TIME'") == "20"
    assert fetch_one(db, "SELECT auto_accept FROM public.restaurant_master WHERE rest_ref = 'SET1'") is True
    assert audit(db) == [("delivery_pickup_minutes", None, 20, ADA, "dashboard"), ("auto_accept", False, True, ADA, "dashboard")]


def test_unchanged_values_write_no_audit(db):
    sid = session(db)
    put(db, sid, False, None, None, get(db, sid)["version"])
    assert audit(db) == []


def test_stale_version_is_refused_without_writing(db):
    sid = session(db)
    v = get(db, sid)["version"]
    put(db, sid, False, 15, None, v)
    out = put(db, sid, True, 40, None, v)  # second admin with the old version
    assert out["result"] == "stale" and out["state"]["delivery"]["minutes"] == 15
    assert len(audit(db)) == 1


@pytest.mark.parametrize("dmin, cmin", [(0, None), (181, None), (None, -5)])
def test_bad_minutes(db, dmin, cmin):
    sid = session(db)
    assert put(db, sid, False, dmin, cmin, get(db, sid)["version"]) == {"result": "bad_minutes"}


def test_enabling_auto_accept_needs_both_effective_defaults_and_rolls_back(db):
    db.execute("DELETE FROM public.ordelo_config WHERE config_key = 'DEFAULT_COLLECTION_PICKUP_TIME'")
    sid = session(db)
    assert put(db, sid, True, 20, None, get(db, sid)["version"]) == {"result": "needs_defaults"}
    assert audit(db) == [] and fetch_one(db, "SELECT auto_accept FROM public.restaurant_master WHERE rest_ref = 'SET1'") is False
    assert put(db, sid, True, 20, 15, get(db, sid)["version"])["result"] == "ok"


def test_reset_to_inherit_clears_the_restaurant_key(db):
    sid = session(db)
    put(db, sid, False, 12, 12, get(db, sid)["version"])
    out = put(db, sid, False, None, 12, get(db, sid)["version"])
    assert out["state"]["delivery"] == {"minutes": 30, "inherited": True, "own": None}


def test_session_binding_and_removed_admin(db):
    sid = session(db)
    other = session(db, phone=BOB, ref="SET2", token="b", cookie="d")
    put(db, other, True, 10, 10, get(db, other)["version"])
    assert fetch_one(db, "SELECT auto_accept FROM public.restaurant_master WHERE rest_ref = 'SET1'") is False  # SET2 only
    db.execute("UPDATE public.restaurant_master SET admins = '{}' WHERE rest_ref = 'SET1'")
    assert get(db, sid) == {"result": "not_authorised"}
    assert put(db, sid, True, 10, 10, "x") == {"result": "not_authorised"}
    assert get(db, "00000000-0000-0000-0000-000000000000") == {"result": "not_authorised"}


@pytest.mark.parametrize("kind, suffix", [("delivery", "DELIVERY"), ("takeaway", "COLLECTION")])
@pytest.mark.parametrize("own, glob, expected", [
    ("20", "30", (20, False)), ("", "30", (30, True)), (" 7 ", "30", (7, False)), ("0", "30", (30, True)),
    ("abc", "30", (30, True)), (None, "30", (30, True)), (None, None, (None, True)), ("15", "x", (15, False)),
])
def test_default_minutes_agree_with_order_creation(db, own, glob, expected, kind, suffix):
    db.execute("DELETE FROM public.ordelo_config WHERE config_key = ANY(%s)", (list(KEYS),))
    if own is not None:
        db.execute("INSERT INTO public.ordelo_config VALUES (%s, %s)", (f"SET1_DEFAULT_{suffix}_PICKUP_TIME", own))
    if glob is not None:
        db.execute("INSERT INTO public.ordelo_config VALUES (%s, %s)", (f"DEFAULT_{suffix}_PICKUP_TIME", glob))
    got = db.execute("SELECT minutes, inherited FROM public.restaurant_default_pickup_minutes('SET1', %s)", (kind,)).fetchone()
    assert got == expected
    db.execute("UPDATE public.restaurant_master SET auto_accept = true WHERE rest_ref = 'SET1'")
    if expected[0] is None:
        with pytest.raises(Exception):
            db.execute("SELECT * FROM public.resolve_initial_restaurant_acceptance('SET1', %s, now())", (kind,))
    else:
        live = db.execute("SELECT pickup_minutes FROM public.resolve_initial_restaurant_acceptance('SET1', %s, now())", (kind,)).fetchone()[0]
        assert live == expected[0]


# ---- sys-admin change list and undo ------------------------------------------------------------------------------------
def test_changes_list_newest_first(db):
    sid = session(db)
    put(db, sid, False, 18, None, get(db, sid)["version"])
    put(db, sid, False, 19, None, get(db, sid)["version"])
    rows = fetch_one(db, "SELECT public.restaurant_settings_changes('set1', 10)")
    assert [r["new_value"] for r in rows] == [19, 18] and rows[0]["via"] == "dashboard"


def test_revert_restores_and_is_audited_once(db):
    sid = session(db)
    put(db, sid, True, 20, None, get(db, sid)["version"])
    auto_id = db.execute("SELECT id FROM public.restaurant_settings_audit WHERE setting = 'auto_accept'").fetchone()[0]
    out = fetch_one(db, "SELECT public.restaurant_setting_revert(%s, 'sys-admin:447700900999')", (auto_id,))
    assert out["result"] == "ok"
    assert fetch_one(db, "SELECT auto_accept FROM public.restaurant_master WHERE rest_ref = 'SET1'") is False
    assert audit(db)[-1] == ("auto_accept", True, False, "sys-admin:447700900999", "sys-admin")
    assert fetch_one(db, "SELECT public.restaurant_setting_revert(%s, 'x')", (auto_id,)) == {"result": "already_reverted"}


def test_revert_refuses_when_changed_since(db):
    sid = session(db)
    put(db, sid, False, 20, None, get(db, sid)["version"])
    first = db.execute("SELECT id FROM public.restaurant_settings_audit ORDER BY id LIMIT 1").fetchone()[0]
    put(db, sid, False, 21, None, get(db, sid)["version"])
    out = fetch_one(db, "SELECT public.restaurant_setting_revert(%s, 'x')", (first,))
    assert out == {"result": "changed_since", "current": 21}


def test_revert_inherit_value_and_unknown_ids(db):
    sid = session(db)
    put(db, sid, False, 20, None, get(db, sid)["version"])
    aid = db.execute("SELECT id FROM public.restaurant_settings_audit").fetchone()[0]
    assert fetch_one(db, "SELECT public.restaurant_setting_revert(%s, 'x')", (aid,))["result"] == "ok"
    assert get(db, sid)["delivery"] == {"minutes": 30, "inherited": True, "own": None}
    assert fetch_one(db, "SELECT public.restaurant_setting_revert(-1, 'x')") == {"result": "not_found"}
    db.execute("INSERT INTO public.restaurant_settings_audit (rest_ref, setting, by_who, via) VALUES ('SET1', 'alert_pause', 'x', 'dashboard')")
    pid = db.execute("SELECT max(id) FROM public.restaurant_settings_audit").fetchone()[0]
    assert fetch_one(db, "SELECT public.restaurant_setting_revert(%s, 'x')", (pid,)) == {"result": "not_revertible"}


@pytest.mark.parametrize("fn", ["rest_admin_acceptance_get(uuid)", "rest_admin_acceptance_set(uuid,boolean,integer,integer,text)",
                                "restaurant_settings_changes(text,integer)", "restaurant_setting_revert(bigint,text)",
                                "restaurant_setting_change(text,text,text,jsonb,text,text,uuid)"])
def test_service_role_only(db, fn):
    for role in ("anon", "authenticated"):
        assert fetch_one(db, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, "public." + fn)) is False
    assert fetch_one(db, "SELECT has_function_privilege('service_role', %s, 'EXECUTE')", ("public." + fn,)) is True
