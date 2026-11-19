"""Operational report on the isolated DB (admin_dashboard/rest_admin_reports.sql).

Decision milestones captured by the summary-table triggers (first decision only, never blocking), the acceptance split
(manual / configured auto / timeout fallback / declined / no answer), the manual acceptance median, the delivery pickup
measures against the original and the latest promise (the owner's 18:45 / 18:30 / 18:50 example: +15 and -5), London
creation-day cohorts, test-order exclusion, session binding and range validation.
"""

from __future__ import annotations

import pytest

from .conftest import fetch_one

pytestmark = pytest.mark.usefixtures("sql_env")

ADA = "447700900971"
H = {c: c * 64 for c in "abcdef"}
UA = "9" * 64
DAY = "2026-11-10"


@pytest.fixture(autouse=True)
def clean(db):
    def wipe():
        db.execute("DELETE FROM public.order_customer_event WHERE order_number LIKE 'REPT-%'")
        db.execute("DELETE FROM public.order_milestone WHERE order_number LIKE 'REPT-%'")
        db.execute("DELETE FROM public.order_item WHERE order_id LIKE 'REPT-%'")
        db.execute("DELETE FROM public.food_order WHERE order_id LIKE 'REPT-%'")
        db.execute("DELETE FROM public.delivery_summary WHERE order_number LIKE 'REPT-%'")
        db.execute("DELETE FROM public.takeaway_summary WHERE order_number LIKE 'REPT-%'")
        db.execute("DELETE FROM public.auth_sessions WHERE principal_id = %s", (ADA,))
        db.execute("DELETE FROM public.restaurant_master WHERE rest_ref = 'REPT'")
    wipe()
    db.execute("INSERT INTO public.restaurant_master (rest_ref, rest_name, admins) VALUES ('REPT', 'Reports', %s)", ([ADA],))
    yield
    wipe()


def session(db):
    db.execute("INSERT INTO public.auth_sessions (role, principal_id, scope_ref, wa_number, token_hash, expires_at)"
               " VALUES ('rest_admin', %s, 'REPT', %s, %s, now() + interval '30 minutes')", (ADA, ADA, H["a"]))
    return fetch_one(db, "SELECT public.admin_dashboard_activate('rest_admin', %s, %s, %s, NULL)", (H["a"], H["c"], UA))["session_id"]


def delivery(db, n, created, rcs="restaurant_unconfirmed", method=None, pickup=None, initial=None, collected=None):
    num = f"REPT-D-{n}"
    db.execute("INSERT INTO public.food_order (order_id, order_number) VALUES (%s, %s)", (num, num))
    db.execute("INSERT INTO public.delivery_summary (order_number, dtts, restaurant_confirmation_status, rest_confirmation_method,"
               " pickup_time, pickup_time_initial, restaurant_update_dtts) VALUES (%s, %s, %s, %s, %s, %s, %s)",
               (num, created, rcs, method, pickup, initial, None))
    if collected:
        db.execute("INSERT INTO public.order_customer_event (order_number, event_key, event_type, occurred_at, is_estimate)"
                   " VALUES (%s, 'food_collected', 'food_collected', %s, false)", (num, collected))
    return num


def report(db, sid, frm=DAY, to=DAY, kind="all"):
    return fetch_one(db, "SELECT public.rest_admin_report_operations(%s, %s, %s, %s)", (sid, frm, to, kind))


def test_capture_stamps_the_first_decision_only_and_never_blocks(db):
    num = delivery(db, 1, f"{DAY} 18:00+00")
    db.execute("UPDATE public.delivery_summary SET restaurant_confirmation_status = 'restaurant_accept' WHERE order_number = %s", (num,))
    first = fetch_one(db, "SELECT at FROM public.order_milestone WHERE order_number = %s AND milestone = 'decided'", (num,))
    db.execute("UPDATE public.delivery_summary SET restaurant_confirmation_status = 'restaurant_pickuptime_adjusted' WHERE order_number = %s", (num,))
    assert fetch_one(db, "SELECT count(*) FROM public.order_milestone WHERE order_number = %s", (num,)) == 1
    assert fetch_one(db, "SELECT at FROM public.order_milestone WHERE order_number = %s", (num,)) == first
    assert fetch_one(db, "SELECT data FROM public.order_milestone WHERE order_number = %s", (num,)) == {"status": "restaurant_accept", "kind": "delivery"}


def test_auto_accept_writes_no_decision_milestone(db):
    num = delivery(db, 2, f"{DAY} 18:00+00")
    db.execute("UPDATE public.delivery_summary SET restaurant_confirmation_status = 'auto_accept' WHERE order_number = %s", (num,))
    assert fetch_one(db, "SELECT count(*) FROM public.order_milestone WHERE order_number = %s", (num,)) == 0


def test_pickup_against_original_and_latest_promise(db):
    sid = session(db)
    # the owner's example: collected 18:45, original promise 18:30, revised 18:50 -> +15 late and 5 early
    delivery(db, 3, f"{DAY} 18:00+00", "restaurant_pickuptime_adjusted", None,
             pickup=f"{DAY} 18:50+00", initial=f"{DAY} 18:30+00", collected=f"{DAY} 18:45+00")
    t = report(db, sid)["totals"]
    assert t["pickup_measured"] == 1 and float(t["to_pickup_median_min"]) == 45.0
    assert float(t["vs_original_median_min"]) == 15.0 and float(t["vs_latest_median_min"]) == -5.0
    assert t["late_vs_original"] == 1 and t["late_vs_latest"] == 0


def test_unchanged_promise_benchmarks_coincide(db):
    sid = session(db)
    delivery(db, 4, f"{DAY} 12:00+00", "restaurant_accept", pickup=f"{DAY} 12:30+00", collected=f"{DAY} 12:40+00")
    t = report(db, sid)["totals"]
    assert float(t["vs_original_median_min"]) == float(t["vs_latest_median_min"]) == 10.0


def test_acceptance_split_and_manual_median(db):
    sid = session(db)
    for n, rcs, method in [(5, "restaurant_unconfirmed", None), (6, "restaurant_unconfirmed", None), (7, "auto_accept", "configured_auto"),
                           (8, "auto_accept", None), (9, "restaurant_decline", None), (10, "restaurant_timedout", None)]:
        delivery(db, n, f"{DAY} 10:00+00", rcs, method)
    # orders 5 and 6 are accepted by a person 2 and 4 minutes after creation (milestones captured by the trigger)
    db.execute("UPDATE public.delivery_summary SET restaurant_confirmation_status = 'restaurant_accept' WHERE order_number IN ('REPT-D-5','REPT-D-6')")
    db.execute("UPDATE public.order_milestone SET at = %s WHERE order_number = 'REPT-D-5'", (f"{DAY} 10:02+00",))
    db.execute("UPDATE public.order_milestone SET at = %s WHERE order_number = 'REPT-D-6'", (f"{DAY} 10:04+00",))
    t = report(db, sid)["totals"]
    assert (t["orders"], t["manual"], t["configured_auto"], t["timeout_auto"], t["declined"], t["no_answer"]) == (6, 2, 1, 1, 1, 1)
    assert t["accept_measured"] == 2 and float(t["accept_median_min"]) == 3.0


def test_london_day_cohort_test_orders_kind_and_range(db):
    sid = session(db)
    delivery(db, 11, "2026-11-10 23:30+00")             # 23:30 London on the 10th (GMT)
    delivery(db, 12, "2026-11-11 00:30+00")             # the 11th
    t = delivery(db, 13, "2026-11-10 12:00+00")
    db.execute("INSERT INTO public.order_item (order_id, product_name) VALUES (%s, 'TEST3100')", (t,))
    db.execute("INSERT INTO public.takeaway_summary (order_number, dtts, restaurant_confirmation_status) VALUES ('REPT-T-1', %s, 'auto_accept')",
               (f"{DAY} 13:00+00",))
    out = report(db, sid)
    assert out["totals"]["orders"] == 2 and out["totals"]["deliveries"] == 1  # 11 + takeaway; 12 is the next day; 13 is a test
    assert report(db, sid, kind="takeaway")["totals"]["orders"] == 1
    assert [d["day"] for d in report(db, sid, "2026-11-10", "2026-11-11")["days"]] == ["2026-11-10", "2026-11-11"]
    assert report(db, sid, "2026-11-11", "2026-11-10") == {"result": "bad_range"}
    assert report(db, sid, "2025-01-01", "2026-11-10") == {"result": "bad_range"}


def test_empty_range_and_removed_admin(db):
    sid = session(db)
    t = report(db, sid, "2026-01-01", "2026-01-02")["totals"]
    assert t["orders"] == 0 and t["accept_median_min"] is None and t["to_pickup_median_min"] is None
    db.execute("UPDATE public.restaurant_master SET admins = '{}' WHERE rest_ref = 'REPT'")
    assert report(db, sid) == {"result": "not_authorised"}
