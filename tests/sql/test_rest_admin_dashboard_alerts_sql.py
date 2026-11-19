"""Restaurant dashboard "My alerts" on the isolated DB (restaurant_admin/rest_admin_dashboard_alerts.sql).

Channels and pauses through the session-bound RPCs: same rules as Telegram /channels, /off, /on (admin_set_channels,
pause_start with the last-admin guard, pause_end), audit rows, the 'dashboard' created_via, and session binding.
"""

from __future__ import annotations

import pytest

from .conftest import fetch_one

pytestmark = pytest.mark.usefixtures("sql_env")

ADA, BOB = "447700900941", "447700900942"
H = {c: c * 64 for c in "abcdef"}
UA = "9" * 64


@pytest.fixture(autouse=True)
def clean(db):
    def wipe():
        db.execute("DELETE FROM public.restaurant_settings_audit WHERE rest_ref = 'ALR1'")
        db.execute("DELETE FROM public.pauses WHERE principal IN (%s, %s)", (ADA, BOB))
        db.execute("DELETE FROM public.auth_sessions WHERE principal_id IN (%s, %s)", (ADA, BOB))
        db.execute("DELETE FROM public.restaurant_admin WHERE phone IN (%s, %s)", (ADA, BOB))
        db.execute("DELETE FROM public.restaurant_master WHERE rest_ref = 'ALR1'")
    wipe()
    db.execute("INSERT INTO public.restaurant_master (rest_ref, rest_name, admins) VALUES ('ALR1', 'Alerts One', %s)", ([ADA, BOB],))
    yield
    wipe()


def session(db, phone=ADA, token="a", cookie="c"):
    db.execute("INSERT INTO public.auth_sessions (role, principal_id, scope_ref, wa_number, token_hash, expires_at)"
               " VALUES ('rest_admin', %s, 'ALR1', %s, %s, now() + interval '30 minutes')", (phone, phone, H[token]))
    return fetch_one(db, "SELECT public.admin_dashboard_activate('rest_admin', %s, %s, %s, NULL)", (H[token], H[cookie], UA))["session_id"]


def link(db, phone, tuid):
    return fetch_one(db, "SELECT public.t_admin_link(%s, %s, %s, 'u', 'F')", (tuid, tuid, phone))


def test_get_for_an_unlinked_admin_defaults_to_whatsapp(db):
    out = fetch_one(db, "SELECT public.rest_admin_alerts_get(%s)", (session(db),))
    assert out["result"] == "ok" and out["channels"] == ["whatsapp"] and out["telegram_linked"] is False
    assert out["pause"] == {"result": "not_paused"} and isinstance(out["pause_options"], list) and out["pause_options"]


def test_channels_follow_the_admin_set_channels_rule_and_are_audited(db):
    sid = session(db)
    assert fetch_one(db, "SELECT public.rest_admin_alerts_set_channels(%s, ARRAY['whatsapp'])", (sid,)) == {"result": "not_found"}
    link(db, ADA, 999000000941)
    out = fetch_one(db, "SELECT public.rest_admin_alerts_set_channels(%s, ARRAY['telegram','whatsapp'])", (sid,))
    assert out == {"result": "ok", "channels": ["telegram", "whatsapp"]}
    assert fetch_one(db, "SELECT channels_set_by FROM public.restaurant_admin WHERE phone = %s", (ADA,)) == "dashboard"
    assert fetch_one(db, "SELECT public.rest_admin_alerts_set_channels(%s, ARRAY['fax'])", (sid,)) == {"result": "bad_channels"}
    rows = db.execute("SELECT setting, old_value, new_value, via FROM public.restaurant_settings_audit WHERE rest_ref = 'ALR1'").fetchall()
    assert rows == [("alert_channels", ["telegram"], ["telegram", "whatsapp"], "dashboard")]


def test_telegram_needs_a_link(db):
    db.execute("INSERT INTO public.restaurant_admin (phone) VALUES (%s)", (ADA,))
    out = fetch_one(db, "SELECT public.rest_admin_alerts_set_channels(%s, ARRAY['telegram'])", (session(db),))
    assert out["result"] == "not_linked"


def test_pause_resume_and_last_admin_guard(db):
    ada, bob = session(db), session(db, phone=BOB, token="b", cookie="d")
    opt = fetch_one(db, "SELECT public.pause_options('rest_admin')")[0]
    out = fetch_one(db, "SELECT public.rest_admin_alerts_pause(%s, %s)", (ada, opt))
    assert out["result"] == "paused"
    assert fetch_one(db, "SELECT created_via FROM public.pauses WHERE principal = %s AND ended_at IS NULL", (ADA,)) == "dashboard"
    assert fetch_one(db, "SELECT public.rest_admin_alerts_get(%s)", (ada,))["pause"]["result"] == "paused"
    assert fetch_one(db, "SELECT public.rest_admin_alerts_pause(%s, %s)", (bob, opt))["result"] == "not_allowed"  # last admin
    assert fetch_one(db, "SELECT public.rest_admin_alerts_pause(%s, 'forever')", (ada,))["result"] == "bad_duration"
    assert fetch_one(db, "SELECT public.rest_admin_alerts_resume(%s)", (ada,))["result"] == "resumed"
    assert fetch_one(db, "SELECT public.rest_admin_alerts_resume(%s)", (ada,))["result"] == "not_paused"
    assert fetch_one(db, "SELECT count(*) FROM public.restaurant_settings_audit WHERE setting = 'alert_pause' AND rest_ref = 'ALR1'") == 2


def test_not_authorised_for_a_removed_admin(db):
    sid = session(db)
    db.execute("UPDATE public.restaurant_master SET admins = %s WHERE rest_ref = 'ALR1'", ([BOB],))
    for sql in ("SELECT public.rest_admin_alerts_get(%s)", "SELECT public.rest_admin_alerts_resume(%s)"):
        assert fetch_one(db, sql, (sid,)) == {"result": "not_authorised"}
    assert fetch_one(db, "SELECT public.rest_admin_alerts_pause(%s, '6h')", (sid,)) == {"result": "not_authorised"}
    assert fetch_one(db, "SELECT public.rest_admin_alerts_set_channels(%s, ARRAY['whatsapp'])", (sid,)) == {"result": "not_authorised"}


@pytest.mark.parametrize("fn", ["rest_admin_alerts_get(uuid)", "rest_admin_alerts_set_channels(uuid,text[])",
                                "rest_admin_alerts_pause(uuid,text)", "rest_admin_alerts_resume(uuid)"])
def test_service_role_only(db, fn):
    for role in ("anon", "authenticated"):
        assert fetch_one(db, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, "public." + fn)) is False
