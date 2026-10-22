"""The rider shift rule (availability/rider_shift.sql) and the WhatsApp-only shift question (dispatch/enquire_shift_availability.sql),
phase R5, on the isolated DB.

Proves: only an 'active' rider can start a shift (D41) and nothing is written otherwise; nobody ends a shift during a job;
'off' keeps shift_response_dtts as the WhatsApp "No" always did; the daily question goes to active WhatsApp riders only
(D53); and the grants.
"""

from __future__ import annotations

import json

import psycopg
import pytest

from .conftest import fetch_one

pytestmark = pytest.mark.usefixtures("sql_env")

ON_WA, ON_TG, NEW, OTHER = "447700900901", "447700900902", "447700900903", "447700900904"


@pytest.fixture(autouse=True)
def riders(db):
    def wipe():
        db.execute("DELETE FROM public.delivery_inflight WHERE rider_id LIKE '4477009009%'")
        db.execute("DELETE FROM public.rider_master WHERE rider_id LIKE '4477009009%'")
        db.execute("DELETE FROM public.http_calls")
    wipe()
    db.execute("INSERT INTO public.rider_master (rider_id, rider_name, status, is_in_shift, channel, tuid, tcid) VALUES"
               " (%s, 'Wanda', 'active', false, 'whatsapp', NULL, NULL), (%s, 'Tom', 'active', true, 'telegram', 1, 1),"
               " (%s, 'Nia', 'inactive', false, 'telegram', 2, 2), (%s, 'Oli', 'Active', true, 'whatsapp', NULL, NULL)",
               (ON_WA, ON_TG, NEW, OTHER))
    yield
    wipe()


def shift(db, rider, on):
    return fetch_one(db, "SELECT public.rider_set_shift(%s, %s)", (rider, on))


def row(db, rider):
    return db.execute("SELECT is_in_shift, shift_response_dtts IS NOT NULL FROM public.rider_master WHERE rider_id = %s",
                      (rider,)).fetchone()


def test_an_active_rider_starts_a_shift(db):
    assert shift(db, ON_WA, True) == {"result": "on"}
    assert row(db, ON_WA) == (True, True)


@pytest.mark.parametrize("rider, status", [(NEW, "inactive"), (OTHER, "Active")])
def test_only_exactly_active_may_start_and_nothing_is_written(db, rider, status):
    before = row(db, rider)
    assert shift(db, rider, True) == {"result": "not_active", "status": status}
    assert row(db, rider) == before


def test_ending_a_shift_during_a_job_is_refused(db):
    db.execute("INSERT INTO public.delivery_inflight (dispatch_id, order_number, rider_id) VALUES (990001, 'ELAS-SHFT-1', %s)", (ON_TG,))
    assert shift(db, ON_TG, False) == {"result": "on_job", "order_number": "ELAS-SHFT-1"}
    assert row(db, ON_TG)[0] is True


def test_ending_a_shift_keeps_the_response_time(db):
    shift(db, ON_WA, True)
    assert shift(db, ON_WA, False) == {"result": "off"}
    assert row(db, ON_WA) == (False, True)
    assert shift(db, NEW, False) == {"result": "off"}  # harmless for a rider who is not active


def test_unknown_rider(db):
    assert shift(db, "447700900999", True) == {"result": "not_found"}
    assert shift(db, "447700900999", False) == {"result": "not_found"}


def test_the_daily_question_goes_to_active_whatsapp_riders_only(db):
    assert fetch_one(db, "SELECT public.enquire_shift_availability()") is True
    (url, body), = db.execute("SELECT url, body FROM public.http_calls").fetchall()
    assert url.endswith("/delivery-hooks/shift-availability-enquiry")
    asked = {r["rider_id"] for r in json.loads(body)["riders"]}
    assert ON_WA in asked and ON_TG not in asked and NEW not in asked and OTHER not in asked


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_public_roles_cannot_call(db, role):
    db.execute(f"SET ROLE {role}")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute("SELECT public.rider_set_shift('447700900901', true)")
    finally:
        db.execute("RESET ROLE")
