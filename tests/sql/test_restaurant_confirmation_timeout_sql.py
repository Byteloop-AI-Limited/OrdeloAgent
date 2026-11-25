"""Isolated-database tests for the confirmation timeout policy and job.

Files under test: ordelo_datamodels/restaurant_admin/restaurant_confirmation_policy.sql and
restaurant_admin/process_restaurant_confirmation.sql (plans/restaurant-confirmation-timeout-action-plan.md).
Covers: policy defaults and per-restaurant / global precedence, silence=decline (auto_decline + declined, delivery and
takeaway), silence=accept unchanged, an accepted-without-pickup order always times out as 'restaurant_timedout',
the timeout minutes, the 15-second pickup grace after an accept (migrations/restaurant_accept_pickup_grace.sql), and that the
restaurant-update trigger fires with 'auto_decline'. Skipped without ORDELO_TEST_DB_URI.
"""

from __future__ import annotations

import pytest

from .conftest import fetch_one

pytestmark = pytest.mark.usefixtures("sql_env")


@pytest.fixture(autouse=True)
def clean(db):
    db.execute("TRUNCATE public.delivery_summary, public.takeaway_summary, public.trigger_log CASCADE")  # wa_location FKs
    db.execute("DELETE FROM public.ordelo_config WHERE config_key LIKE '%RESTAURANT_CONFIRMATION_TIMEOUT%'")


def config(db, key, value):
    db.execute(
        "INSERT INTO public.ordelo_config (config_key, config_value) VALUES (%s, %s) "
        "ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value", (key, value))


def old_order(db, kind="delivery", number="ZZZZ-1", minutes_old=10, rcs="restaurant_unconfirmed", pickup=False,
              accepted_secs_ago=None):
    """accepted_secs_ago sets restaurant_update_dtts, the stamp restaurant_order_decide() writes on accept."""
    db.execute(
        f"INSERT INTO public.{kind}_summary (order_number, dtts, restaurant_confirmation_status, pickup_time, restaurant_update_dtts) "
        "VALUES (%s, now() - %s::numeric * interval '1 minute', %s, %s, "
        "now() - %s::numeric * interval '1 second')",
        (number, minutes_old, rcs, "2026-11-16 12:30:00+00" if pickup else None, accepted_secs_ago))
    db.execute("TRUNCATE public.trigger_log")  # the INSERT trigger is not what these tests are about
    return number


def run_job(db):
    return [r[0] for r in db.execute("SELECT * FROM public.process_restaurant_confirmation()").fetchall()]


def state(db, kind, number):
    return db.execute(
        f"SELECT restaurant_confirmation_status, status, restaurant_update_dtts IS NOT NULL FROM public.{kind}_summary WHERE order_number = %s",
        (number,)).fetchone()


# ---- the policy function --------------------------------------------------------------------------


def test_policy_defaults_to_five_minutes_and_accept(db):
    assert db.execute("SELECT * FROM public.restaurant_confirmation_policy('ZZZZ')").fetchone() == (5, "accept")


def test_policy_per_restaurant_beats_global(db):
    config(db, "RESTAURANT_CONFIRMATION_TIMEOUT_TIME", "7")
    config(db, "ZZZZ_RESTAURANT_CONFIRMATION_TIMEOUT_TIME", "3")
    assert db.execute("SELECT timeout_minutes FROM public.restaurant_confirmation_policy('ZZZZ')").fetchone()[0] == 3
    assert db.execute("SELECT timeout_minutes FROM public.restaurant_confirmation_policy('OTHR')").fetchone()[0] == 7


@pytest.mark.parametrize("value, expected", [("decline", "decline"), (" Decline ", "decline"), ("DECLINE", "decline"),
                                             ("accept", "accept"), ("", "accept"), ("banana", "accept")])
def test_policy_action_is_decline_only_for_the_word_decline(db, value, expected):
    config(db, "ZZZZ_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION", value)
    assert db.execute("SELECT timeout_action FROM public.restaurant_confirmation_policy('ZZZZ')").fetchone()[0] == expected


def test_policy_action_is_per_restaurant_only(db):
    config(db, "ZZZZ_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION", "decline")
    assert db.execute("SELECT timeout_action FROM public.restaurant_confirmation_policy('OTHR')").fetchone()[0] == "accept"


# ---- the job: silence means decline ---------------------------------------------------------------


@pytest.mark.parametrize("kind", ["delivery", "takeaway"])
@pytest.mark.parametrize("sweep_first", [False, True])
def test_two_minute_policy_acceptance_races_with_sweep(db, kind, sweep_first):
    config(db, "ZZZZ_RESTAURANT_CONFIRMATION_TIMEOUT_TIME", "2")
    config(db, "ZZZZ_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION", "decline")
    number = old_order(db, kind, minutes_old="2.05")  # 2:03
    if sweep_first:
        run_job(db)
    decision = fetch_one(
        db, "SELECT public.restaurant_order_decide(%s, %s, 'accept', '447700900123', 'test')",
        (number, kind),
    )
    assert decision["result"] == ("already_decided" if sweep_first else "ok")
    assert state(db, kind, number)[0] == ("auto_decline" if sweep_first else "restaurant_accept")


@pytest.mark.parametrize("kind", ["delivery", "takeaway"])
def test_silence_declines_when_policy_says_decline(db, kind):
    config(db, "ZZZZ_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION", "decline")
    config(db, "ZZZZ_RESTAURANT_CONFIRMATION_TIMEOUT_TIME", "3")
    n = old_order(db, kind, minutes_old=4)
    assert len(run_job(db)) == 1
    assert state(db, kind, n) == ("auto_decline", "declined", True)
    assert db.execute("SELECT reason FROM public.trigger_log WHERE order_number = %s", (n,)).fetchall() == [("auto_decline",)]


@pytest.mark.parametrize("kind", ["delivery", "takeaway"])
def test_silence_is_not_declined_before_the_timeout(db, kind):
    config(db, "ZZZZ_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION", "decline")
    config(db, "ZZZZ_RESTAURANT_CONFIRMATION_TIMEOUT_TIME", "3")
    n = old_order(db, kind, minutes_old=2)
    assert run_job(db) == []
    assert state(db, kind, n)[:2] == ("restaurant_unconfirmed", "restaurant_unconfirmed")


@pytest.mark.parametrize("kind", ["delivery", "takeaway"])
def test_silence_still_times_out_as_before_without_the_action_key(db, kind):
    n = old_order(db, kind, minutes_old=10)
    run_job(db)
    assert state(db, kind, n)[:2] == ("restaurant_timedout", "restaurant_unconfirmed")


@pytest.mark.parametrize("kind", ["delivery", "takeaway"])
def test_accepted_without_pickup_times_out_even_when_policy_is_decline(db, kind):
    config(db, "ZZZZ_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION", "decline")
    n = old_order(db, kind, minutes_old=10, rcs="restaurant_accept")
    run_job(db)
    assert state(db, kind, n)[:2] == ("restaurant_timedout", "restaurant_unconfirmed")


# ---- the 15-second pickup grace after an accept --------------------------------------------------


@pytest.mark.parametrize("kind", ["delivery", "takeaway"])
def test_accepted_without_pickup_times_out_15_seconds_after_the_accept(db, kind):
    config(db, "ZZZZ_RESTAURANT_CONFIRMATION_TIMEOUT_TIME", "3")
    n = old_order(db, kind, minutes_old=0.5, rcs="restaurant_accept", accepted_secs_ago=20)
    run_job(db)
    assert state(db, kind, n)[:2] == ("restaurant_timedout", "restaurant_unconfirmed")


@pytest.mark.parametrize("kind", ["delivery", "takeaway"])
def test_accepted_within_the_grace_is_left_alone(db, kind):
    config(db, "ZZZZ_RESTAURANT_CONFIRMATION_TIMEOUT_TIME", "3")
    n = old_order(db, kind, minutes_old=0.5, rcs="restaurant_accept", accepted_secs_ago=5)
    assert run_job(db) == []
    assert state(db, kind, n)[0] == "restaurant_accept"


@pytest.mark.parametrize("kind", ["delivery", "takeaway"])
def test_grace_does_not_apply_to_unanswered_orders(db, kind):
    config(db, "ZZZZ_RESTAURANT_CONFIRMATION_TIMEOUT_TIME", "3")
    config(db, "ZZZZ_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION", "decline")
    n = old_order(db, kind, minutes_old=0.5, accepted_secs_ago=20)  # unconfirmed, even with a stamp
    assert run_job(db) == []
    assert state(db, kind, n)[0] == "restaurant_unconfirmed"


@pytest.mark.parametrize("kind", ["delivery", "takeaway"])
def test_accepted_with_pickup_time_ignores_the_grace(db, kind):
    n = old_order(db, kind, minutes_old=0.5, rcs="restaurant_accept", pickup=True, accepted_secs_ago=60)
    assert run_job(db) == []
    assert state(db, kind, n)[0] == "restaurant_accept"


@pytest.mark.parametrize("kind", ["delivery", "takeaway"])
def test_accepted_without_a_stamp_falls_back_to_the_usual_timeout(db, kind):
    config(db, "ZZZZ_RESTAURANT_CONFIRMATION_TIMEOUT_TIME", "3")
    n = old_order(db, kind, minutes_old=0.5, rcs="restaurant_accept")
    assert run_job(db) == []
    assert state(db, kind, n)[0] == "restaurant_accept"


def test_order_with_pickup_time_is_left_alone(db):
    config(db, "ZZZZ_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION", "decline")
    n = old_order(db, "delivery", minutes_old=10, rcs="restaurant_accept", pickup=True)
    assert run_job(db) == []
    assert state(db, "delivery", n)[0] == "restaurant_accept"


def test_job_message_names_the_new_status(db):
    config(db, "ZZZZ_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION", "decline")
    old_order(db, "delivery", minutes_old=10)
    assert "auto_decline" in run_job(db)[0]


def test_job_is_scheduled_by_the_file(db):
    assert fetch_one(db, "SELECT count(*) FROM cron.job WHERE jobname = 'process_restaurant_confirmation'") == 1
