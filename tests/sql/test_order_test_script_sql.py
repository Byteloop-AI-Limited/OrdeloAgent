"""The re-runnable STRK test-order script (ordelo_datamodels/test_support/test_create_t_order_alerts.sql) on the isolated DB."""

from __future__ import annotations

import pytest

from .conftest import ROOT, fetch_one

pytestmark = pytest.mark.usefixtures("sql_env")

SCRIPT = (ROOT / "ordelo_datamodels" / "test_support" / "test_create_t_order_alerts.sql").read_text()
ADMIN = "447448440754"

# The minimal test schema keeps only the summary columns the migrations use; add the NOT-NULL-in-production ones.
EXTRA_COLUMNS = (
    "rest_lon double precision", "rest_lat double precision", "rest_address text", "town text",
    "customer_name text", "customer_lon double precision", "customer_lat double precision",
    "customer_address text", "rest_confirmation_code int", "cust_confirmation_code int",
)


@pytest.fixture(autouse=True)
def schema(db):
    for col in EXTRA_COLUMNS:
        db.execute(f"ALTER TABLE public.delivery_summary ADD COLUMN IF NOT EXISTS {col}")
    db.execute("TRUNCATE public.delivery_summary, public.takeaway_summary, public.t_invites, public.restaurant_master, "
               "public.t_order_alerts, public.t_sent_messages, public.http_calls CASCADE")
    db.execute("UPDATE public.http_stub_status SET status = 200")
    db.execute("INSERT INTO public.restaurant_master (rest_ref, rest_name, admins) VALUES ('STRK', 'Strikers Sports Bar', %s)", ([ADMIN],))
    db.execute("INSERT INTO public.restaurant_master (rest_ref, rest_name, admins) VALUES ('ELAS', 'Elas', %s)", ([ADMIN],))


def link(db):
    db.execute("INSERT INTO public.t_invites (rest_ref, phone_number, status, claimed_at, telegram_user_id, telegram_chat_id, telegram_first_name) "
               "VALUES ('STRK', %s, 'claimed', now(), 111, 111, 'Lohith')", (ADMIN,))


def run(db):
    return db.execute(SCRIPT)


def orders(db):
    return [r[0] for r in db.execute("SELECT order_number FROM public.delivery_summary ORDER BY 1").fetchall()]


def test_inserts_an_unconfirmed_order_and_reports_destinations(db):
    link(db)
    run(db)
    (o,) = orders(db)
    assert o.startswith("STRK-TEST-")
    row = db.execute("SELECT restaurant_confirmation_status, status, rest_ref, pickup_time, restaurant_admin FROM public.delivery_summary").fetchone()
    assert row == ("restaurant_unconfirmed", "restaurant_unconfirmed", "STRK", None, None)
    assert fetch_one(db, "SELECT count(*) FROM public.t_order_card_destinations('rest_admin', 'STRK')") == 1


def test_the_sweep_picks_it_up_and_the_card_flow_works_end_to_end(db):
    link(db)
    run(db)
    (o,) = orders(db)
    assert fetch_one(db, "SELECT public.job_t_order_alerts()") is True
    body = db.execute("SELECT body FROM public.http_calls").fetchone()[0]
    assert o in body and '"n": 1' in body.replace('":1', '": 1')
    # the Telegram accept works on it (D14: claimed invite for STRK + phone in admins)
    r = fetch_one(db, "SELECT public.t_order_decide('rest_admin', 111, %s, 'delivery', 'accept')", (o,))
    assert r["result"] == "ok"


def test_rerun_wipes_earlier_test_orders_and_all_their_bookkeeping(db):
    import time

    link(db)
    run(db)
    (first,) = orders(db)
    fetch_one(db, "SELECT public.job_t_order_alerts()")
    db.execute("SELECT public.t_order_card_sent('rest_admin', 111, 5, 111, %s, 'delivery', 'STRK', 'awaiting')", (first,))
    fetch_one(db, "SELECT public.t_order_decide('rest_admin', 111, %s, 'delivery', 'accept')", (first,))
    assert fetch_one(db, "SELECT count(*) FROM public.t_order_alerts") == 4
    assert fetch_one(db, "SELECT count(*) FROM public.t_sent_messages") == 1
    time.sleep(1.1)  # a new second -> a new order number
    run(db)
    (second,) = orders(db)
    assert second != first
    assert fetch_one(db, "SELECT count(*) FROM public.t_order_alerts") == 0
    assert fetch_one(db, "SELECT count(*) FROM public.t_sent_messages") == 0
    assert db.execute("SELECT restaurant_confirmation_status, pickup_time, restaurant_admin FROM public.delivery_summary").fetchone() == ("restaurant_unconfirmed", None, None)
    fetch_one(db, "SELECT public.job_t_order_alerts()")  # reseeds from scratch
    assert fetch_one(db, "SELECT count(*) FROM public.t_order_alerts") == 4


def test_same_second_rerun_is_still_clean(db):
    link(db)
    run(db)
    run(db)
    assert len(orders(db)) == 1


def test_only_test_orders_are_touched(db):
    link(db)
    db.execute("INSERT INTO public.delivery_summary (order_number, rest_lon, rest_lat, rest_address, town, customer_name, customer_lon, "
               "customer_lat, customer_address, rest_confirmation_code, cust_confirmation_code) "
               "VALUES ('ELAS-REAL-1', 0,0,'a','t','c',0,0,'a',1,1)")
    db.execute("INSERT INTO public.t_order_alerts (order_number, order_type, rest_ref, offset_secs, n, of_n, due_at) VALUES ('ELAS-REAL-1','delivery','ELAS',0,1,1,now())")
    db.execute("INSERT INTO public.t_sent_messages (bot_key, tcid, message_id, subject_type, subject_ref, kind) VALUES ('rest_admin', 9, 9, 'order', 'ELAS-REAL-1', 'order_card')")
    run(db)
    assert "ELAS-REAL-1" in orders(db)
    assert fetch_one(db, "SELECT count(*) FROM public.t_order_alerts WHERE order_number = 'ELAS-REAL-1'") == 1
    assert fetch_one(db, "SELECT count(*) FROM public.t_sent_messages WHERE subject_ref = 'ELAS-REAL-1'") == 1


def test_no_food_order_or_delivery_detail_is_created(db):
    link(db)
    run(db)
    assert fetch_one(db, "SELECT count(*) FROM public.food_order") == 0


def test_destinations_zero_when_no_one_is_linked(db):
    run(db)
    assert fetch_one(db, "SELECT count(*) FROM public.t_order_card_destinations('rest_admin', 'STRK')") == 0
