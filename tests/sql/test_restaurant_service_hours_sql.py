"""Service hours with one-date overrides on the isolated DB (restaurant_admin/restaurant_service_hours.sql).

The shared reading rule (override replaces the weekday for that London date, the all-day marker, overnight spill, no spill
into an overridden date, DST), the order-guard question restaurant_closed_by_override(), interval validation, the rollout
gate, and the dashboard editor RPCs (close all day, close early, special hours, clear, weekly) with their audit rows.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from .conftest import fetch_one

pytestmark = pytest.mark.usefixtures("sql_env")

ADA = "447700900951"
H = {c: c * 64 for c in "abcdef"}
UA = "9" * 64
WEEK = {d: [["12:00", "22:00"]] for d in ("mon", "tue", "wed", "thu", "sun")}
WEEK.update({"fri": [["12:00", "25:00"]], "sat": [["12:00", "23:00"]]})  # Friday runs to 01:00 Saturday


@pytest.fixture(autouse=True)
def clean(db):
    def wipe():
        db.execute("DELETE FROM public.restaurant_settings_audit WHERE rest_ref = 'HRS1'")
        db.execute("DELETE FROM public.auth_sessions WHERE principal_id = %s", (ADA,))
        db.execute("DELETE FROM public.restaurant_master WHERE rest_ref = 'HRS1'")
        db.execute("DELETE FROM public.ordelo_config WHERE config_key = 'REST_DASHBOARD_HOURS_EDITS'")
    wipe()
    db.execute("INSERT INTO public.restaurant_master (rest_ref, rest_name, admins, service_hours_json) VALUES ('HRS1', 'Hours', %s, %s)",
               ([ADA], json.dumps(WEEK)))
    yield
    wipe()


def set_hours(db, hours):
    db.execute("UPDATE public.restaurant_master SET service_hours_json = %s WHERE rest_ref = 'HRS1'", (json.dumps(hours),))


def open_at(db, at, use_dates=True):
    return fetch_one(db, "SELECT public.service_hours_open(service_hours_json, %s::timestamptz, %s) FROM public.restaurant_master"
                         " WHERE rest_ref = 'HRS1'", (at, use_dates))


def closed_by_override(db, at):
    return fetch_one(db, "SELECT public.restaurant_closed_by_override('HRS1', %s::timestamptz)", (at,))


# 2026-12-04 is a Friday, 12-05 Saturday; London is on GMT in December.
def test_weekly_rule_and_overnight_spill(db):
    assert open_at(db, "2026-12-04 13:00+00") is True
    assert open_at(db, "2026-12-04 11:59+00") is False
    assert open_at(db, "2026-12-05 00:30+00") is True    # Friday's 25:00 spills into Saturday
    assert open_at(db, "2026-12-05 01:00+00") is False


def test_all_day_marker_closes_the_date_and_blocks_the_spill_into_it(db):
    set_hours(db, {**WEEK, "dates": {"2026-12-05": [["00:00", "00:01"]]}})
    assert open_at(db, "2026-12-05 00:00:30+00") is False   # the marker is not a real minute of opening
    assert open_at(db, "2026-12-05 00:30+00") is False      # Friday's spill does not enter an overridden date
    assert open_at(db, "2026-12-05 15:00+00") is False
    assert open_at(db, "2026-12-04 23:30+00") is True       # Friday itself is untouched
    assert open_at(db, "2026-12-12 15:00+00") is True       # the next Saturday is normal again
    assert closed_by_override(db, "2026-12-05 15:00+00") is True
    assert closed_by_override(db, "2026-12-05 09:00+00") is False  # weekly hours were closed anyway: no new refusal


def test_early_close_and_special_hours_past_midnight(db):
    set_hours(db, {**WEEK, "dates": {"2026-12-03": [["12:00", "18:00"]], "2026-12-06": [["10:00", "26:00"]]}})
    assert open_at(db, "2026-12-03 17:59+00") is True and open_at(db, "2026-12-03 18:00+00") is False
    assert closed_by_override(db, "2026-12-03 19:00+00") is True
    assert open_at(db, "2026-12-07 01:30+00") is True       # an override's own hours run past midnight


def test_bst_dates_use_london_time(db):
    set_hours(db, {**WEEK, "dates": {"2026-07-03": [["00:00", "00:01"]]}})  # Friday in BST
    assert open_at(db, "2026-07-02 23:30+00") is False      # 00:30 London on the 3rd: closed date, no Thursday spill
    assert open_at(db, "2026-07-02 22:30+00") is False      # 23:30 London on the 2nd (Thursday closes 22:00)
    assert open_at(db, "2026-07-02 20:30+00") is True       # 21:30 London Thursday


def test_malformed_hours_never_refuse_an_order(db):
    set_hours(db, {**WEEK, "dates": {"2026-12-05": [["xx", "yy"]]}})
    assert closed_by_override(db, "2026-12-05 15:00+00") is False
    assert fetch_one(db, "SELECT public.restaurant_closed_by_override('NONE', now())") is False


@pytest.mark.parametrize("intervals, ok", [
    ([["12:00", "22:00"]], True), ([["00:00", "00:01"]], True), ([], True), ([["18:00", "26:30"]], True),
    ([["12:00", "11:00"]], False), ([["24:00", "25:00"]], False), ([["12:00", "49:00"]], False),
    ([["12:00", "15:00"], ["14:00", "18:00"]], False), ([["1200", "1500"]], False), ("x", False),
])
def test_interval_validation(db, intervals, ok):
    assert fetch_one(db, "SELECT public.service_hours_valid_day(%s::jsonb)", (json.dumps(intervals),)) is ok


# ---- dashboard editor ------------------------------------------------------------------------------------------------
def session(db):
    db.execute("INSERT INTO public.auth_sessions (role, principal_id, scope_ref, wa_number, token_hash, expires_at)"
               " VALUES ('rest_admin', %s, 'HRS1', %s, %s, now() + interval '30 minutes')", (ADA, ADA, H["a"]))
    return fetch_one(db, "SELECT public.admin_dashboard_activate('rest_admin', %s, %s, %s, NULL)", (H["a"], H["c"], UA))["session_id"]


def london_today(db):
    return fetch_one(db, "SELECT (now() AT TIME ZONE 'Europe/London')::date")


def stored(db):
    return fetch_one(db, "SELECT service_hours_json FROM public.restaurant_master WHERE rest_ref = 'HRS1'")


def test_writes_are_refused_until_the_gate_lists_the_restaurant(db):
    sid = session(db)
    d = london_today(db) + timedelta(days=3)
    assert fetch_one(db, "SELECT public.rest_admin_hours_get(%s)", (sid,))["editable"] is False
    assert fetch_one(db, "SELECT public.rest_admin_hours_close_date(%s, %s, NULL)", (sid, d)) == {"result": "disabled"}
    db.execute("INSERT INTO public.ordelo_config VALUES ('REST_DASHBOARD_HOURS_EDITS', 'strk, hrs1')")
    assert fetch_one(db, "SELECT public.rest_admin_hours_get(%s)", (sid,))["editable"] is True


def test_close_all_day_early_close_clear_and_audit(db):
    db.execute("INSERT INTO public.ordelo_config VALUES ('REST_DASHBOARD_HOURS_EDITS', 'all')")
    sid = session(db)
    today = london_today(db)
    holiday = today + timedelta(days=(4 - today.weekday()) % 7 + 7)       # a Friday 1-2 weeks out
    early = holiday - timedelta(days=1)                                   # the Thursday before
    out = fetch_one(db, "SELECT public.rest_admin_hours_close_date(%s, %s, NULL)", (sid, holiday))
    assert out["result"] == "ok" and out["intervals"] == [["00:00", "00:01"]]
    out = fetch_one(db, "SELECT public.rest_admin_hours_close_date(%s, %s, '17:30')", (sid, early))
    assert out["intervals"] == [["12:00", "17:30"]]
    dates = stored(db)["dates"]
    assert dates == {holiday.isoformat(): [["00:00", "00:01"]], early.isoformat(): [["12:00", "17:30"]]}
    assert stored(db)["thu"] == [["12:00", "22:00"]]                       # the weekly rule is untouched
    got = fetch_one(db, "SELECT public.rest_admin_hours_get(%s)", (sid,))
    assert set(got["dates"]) == {holiday.isoformat(), early.isoformat()} and got["weekly"]["fri"] == [["12:00", "25:00"]]
    assert fetch_one(db, "SELECT public.rest_admin_hours_close_date(%s, %s, NULL)", (sid, holiday)) == {"result": "unchanged"}
    assert fetch_one(db, "SELECT public.rest_admin_hours_clear_date(%s, %s)", (sid, holiday))["result"] == "ok"
    assert fetch_one(db, "SELECT public.rest_admin_hours_clear_date(%s, %s)", (sid, early))["result"] == "ok"
    assert "dates" not in stored(db)                                       # back to the weekly-only shape
    rows = db.execute("SELECT setting, setting_key, old_value, new_value FROM public.restaurant_settings_audit"
                      " WHERE rest_ref = 'HRS1' ORDER BY id").fetchall()
    assert [r[0] for r in rows] == ["hours_date"] * 4 and rows[2][3] is None


def test_early_close_before_opening_is_closed_all_day(db):
    db.execute("INSERT INTO public.ordelo_config VALUES ('REST_DASHBOARD_HOURS_EDITS', 'all')")
    sid = session(db)
    d = london_today(db) + timedelta(days=2)
    assert fetch_one(db, "SELECT public.rest_admin_hours_close_date(%s, %s, '09:00')", (sid, d))["intervals"] == [["00:00", "00:01"]]


@pytest.mark.parametrize("offset, from_, result", [(-1, None, "bad_date"), (91, None, "bad_date"), (2, "25:00", "bad_time"),
                                                   (2, "7pm", "bad_time")])
def test_editor_refusals(db, offset, from_, result):
    db.execute("INSERT INTO public.ordelo_config VALUES ('REST_DASHBOARD_HOURS_EDITS', 'all')")
    sid = session(db)
    d = london_today(db) + timedelta(days=offset)
    assert fetch_one(db, "SELECT public.rest_admin_hours_close_date(%s, %s, %s)", (sid, d, from_)) == {"result": result}


def test_special_hours_and_weekly_edit_and_undo(db):
    db.execute("INSERT INTO public.ordelo_config VALUES ('REST_DASHBOARD_HOURS_EDITS', 'all')")
    sid = session(db)
    d = london_today(db) + timedelta(days=5)
    assert fetch_one(db, "SELECT public.rest_admin_hours_set_date(%s, %s, %s::jsonb)",
                     (sid, d, json.dumps([["10:00", "14:00"]])))["result"] == "ok"
    assert fetch_one(db, "SELECT public.rest_admin_hours_set_date(%s, %s, %s::jsonb)",
                     (sid, d, json.dumps([["14:00", "10:00"]]))) == {"result": "bad_intervals"}
    assert fetch_one(db, "SELECT public.rest_admin_hours_set_weekly(%s, 'mon', %s::jsonb)",
                     (sid, json.dumps([["11:00", "21:00"]])))["result"] == "ok"
    assert fetch_one(db, "SELECT public.rest_admin_hours_set_weekly(%s, 'funday', '[]'::jsonb)", (sid,)) == {"result": "bad_day"}
    assert stored(db)["mon"] == [["11:00", "21:00"]]
    weekly_id = db.execute("SELECT id FROM public.restaurant_settings_audit WHERE setting = 'hours_weekly'").fetchone()[0]
    assert fetch_one(db, "SELECT public.restaurant_setting_revert(%s, 'sys-admin:x')", (weekly_id,))["result"] == "ok"
    assert stored(db)["mon"] == [["12:00", "22:00"]]


def test_removed_admin_cannot_edit(db):
    db.execute("INSERT INTO public.ordelo_config VALUES ('REST_DASHBOARD_HOURS_EDITS', 'all')")
    sid = session(db)
    db.execute("UPDATE public.restaurant_master SET admins = '{}' WHERE rest_ref = 'HRS1'")
    assert fetch_one(db, "SELECT public.rest_admin_hours_get(%s)", (sid,)) == {"result": "not_authorised"}
    assert fetch_one(db, "SELECT public.rest_admin_hours_close_date(%s, %s, NULL)",
                     (sid, date.today() + timedelta(days=2))) == {"result": "not_authorised"}
