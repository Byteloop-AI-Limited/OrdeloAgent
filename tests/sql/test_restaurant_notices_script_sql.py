"""The fake-row harness ordelo_datamodels/misc_sql/test_restaurant_notices.sql on the isolated DB.

Runs each stage the way the owner will (one block at a time) and proves: it leaves the rows it promises, a re-run is clean,
it touches ONLY STRK-TEST-% rows and dummy-town data, every fake order carries the TEST3100 item (so payment_mode = 'test'),
and the rows it creates are enough for the real receipt functions (t_receipt_snapshot / t_receipt_status) to draw a receipt.
Stage 6 (dispatch_cancel_before_pickup) and the commented parts of stage 7 need functions that live only in the real
database; they are checked as text. Nothing here talks to a shared database."""

from __future__ import annotations

import re
import time

import pytest

from .conftest import ROOT, fetch_one

pytestmark = pytest.mark.usefixtures("sql_env")

SCRIPT = (ROOT / "ordelo_datamodels" / "misc_sql" / "test_restaurant_notices.sql").read_text()
ADMIN = "447448440754"
BOT = "rest_admin"
REAL_FUNCTION = (ROOT / "ordelo_datamodels" / "jobs_n_functions" / "create_food_order_with_items.sql").read_text()

# Columns / tables the minimal test schema leaves out but the harness (and the real tables) have. Shapes copied from
# ordelo_datamodels/summary.sql, takeaway_summary.sql, detail.sql, masterdata.sql, food_order.sql.
SCHEMA = """
ALTER TABLE public.restaurant_master ADD COLUMN IF NOT EXISTS rest_id varchar(12) UNIQUE;
ALTER TABLE public.delivery_summary
    ADD COLUMN IF NOT EXISTS rest_lon double precision, ADD COLUMN IF NOT EXISTS rest_lat double precision,
    ADD COLUMN IF NOT EXISTS rest_address text, ADD COLUMN IF NOT EXISTS town text, ADD COLUMN IF NOT EXISTS customer_name text,
    ADD COLUMN IF NOT EXISTS customer_lon double precision, ADD COLUMN IF NOT EXISTS customer_lat double precision,
    ADD COLUMN IF NOT EXISTS cust_confirmation_code int;
ALTER TABLE public.takeaway_summary
    ADD COLUMN IF NOT EXISTS rest_address text, ADD COLUMN IF NOT EXISTS town text, ADD COLUMN IF NOT EXISTS customer_name text;
ALTER TABLE public.food_order
    ADD COLUMN IF NOT EXISTS seq_id int, ADD COLUMN IF NOT EXISTS thread_id text, ADD COLUMN IF NOT EXISTS action text,
    ADD COLUMN IF NOT EXISTS origin_channel text NOT NULL DEFAULT 'whatsapp', ADD COLUMN IF NOT EXISTS storefront text NOT NULL DEFAULT 'direct',
    ADD COLUMN IF NOT EXISTS payment_mode text, ADD COLUMN IF NOT EXISTS idempotency_key text,
    ADD COLUMN IF NOT EXISTS final_order_value float, ADD COLUMN IF NOT EXISTS rest_cost float,
    ADD COLUMN IF NOT EXISTS service_charge float, ADD COLUMN IF NOT EXISTS delivery_fee float;
ALTER TABLE public.order_item ADD COLUMN IF NOT EXISTS sku text;
ALTER TABLE public.rider_master
    ADD COLUMN IF NOT EXISTS vehicle_type varchar(15), ADD COLUMN IF NOT EXISTS town varchar(255),
    ADD COLUMN IF NOT EXISTS is_in_shift boolean NOT NULL DEFAULT true, ADD COLUMN IF NOT EXISTS priority int NOT NULL DEFAULT 1;
CREATE TABLE IF NOT EXISTS public.delivery_detail (
    order_number varchar(100), customer_id varchar(12) NOT NULL, vehicle_type varchar(15) NOT NULL, town varchar(255) NOT NULL,
    rider_payout double precision NOT NULL, distance double precision NOT NULL, status varchar(50) NOT NULL,
    dispatch_id int, rider_id varchar(12), PRIMARY KEY (order_number, vehicle_type));
ALTER TABLE public.delivery_dispatch ADD COLUMN IF NOT EXISTS rider_payout double precision, ADD COLUMN IF NOT EXISTS vehicle_type varchar(15),
    ADD COLUMN IF NOT EXISTS distance double precision, ADD COLUMN IF NOT EXISTS dtts timestamp NOT NULL DEFAULT now();
CREATE TABLE IF NOT EXISTS public.rider_pickup_alert (
    dispatch_id int NOT NULL REFERENCES public.delivery_dispatch(dispatch_id) ON DELETE CASCADE, phase varchar(20) NOT NULL,
    audience varchar(20) NOT NULL, offset_minutes int NOT NULL, order_number varchar(100) NOT NULL, rider_id varchar(12) NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'pending', due_dtts timestamptz NOT NULL DEFAULT now(), sent_dtts timestamptz,
    PRIMARY KEY (dispatch_id, phase, audience, offset_minutes));
CREATE TABLE IF NOT EXISTS public.order_customer_event (
    id bigserial PRIMARY KEY, order_number text NOT NULL REFERENCES public.food_order(order_number) ON DELETE CASCADE,
    event_key text NOT NULL, event_type text NOT NULL, occurred_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS public.order_notification_subscription (
    id bigserial PRIMARY KEY, order_number text NOT NULL REFERENCES public.food_order(order_number) ON DELETE CASCADE,
    channel text NOT NULL, destination text);
CREATE TABLE IF NOT EXISTS public.notification_outbox (
    id bigserial PRIMARY KEY, event_id bigint NOT NULL REFERENCES public.order_customer_event(id) ON DELETE CASCADE,
    subscription_id bigint NOT NULL REFERENCES public.order_notification_subscription(id) ON DELETE CASCADE);
"""

TABLES = ["food_order", "order_item", "delivery_summary", "takeaway_summary", "delivery_detail", "delivery_dispatch",
          "delivery_inflight", "rider_pickup_alert", "order_customer_event", "order_notification_subscription",
          "notification_outbox", "t_order_alerts", "t_sent_messages", "t_invites", "restaurant_master", "rider_master",
          "ordelo_config"]


@pytest.fixture(autouse=True)
def schema(db):
    db.execute(SCHEMA)
    db.execute(REAL_FUNCTION)  # the REAL create_food_order_with_items: payment_mode is derived exactly as in production
    db.execute("TRUNCATE " + ", ".join(f"public.{t}" for t in TABLES) + " RESTART IDENTITY CASCADE")
    db.execute("INSERT INTO public.restaurant_master (rest_ref, rest_id, rest_name, admins) VALUES ('STRK', 'STRK01', 'Strikers Sports Bar', %s)", ([ADMIN],))
    db.execute("INSERT INTO public.restaurant_master (rest_ref, rest_name, admins) VALUES ('ELAS', 'Elas', %s)", ([ADMIN],))
    db.execute("INSERT INTO public.rider_master (rider_id, rider_name, vehicle_type, town) VALUES ('RIDER01', 'Sam', 'bike', 'dummy')")


def stages() -> dict[str, str]:
    """{'PREREQUISITES CHECK (read only)': sql, 'STAGE 0': sql, ...} split on the '-- ===== ... =====' markers."""
    parts = re.split(r"^-- ===== (.+?) =====\s*$", SCRIPT, flags=re.M)
    out = {}
    for title, body in zip(parts[1::2], parts[2::2]):
        out[title.split(":")[0].strip()] = body
    return out


STAGES = stages()


def run(db, name: str):
    return db.execute(STAGES[name])


def link(db):
    db.execute("INSERT INTO public.t_invites (rest_ref, phone_number, status, claimed_at, telegram_user_id, telegram_chat_id, telegram_first_name) "
               "VALUES ('STRK', %s, 'claimed', now(), 111, 111, 'Lohith')", (ADMIN,))


def counts(db) -> dict:
    return {t: fetch_one(db, f"SELECT count(*) FROM public.{t}") for t in TABLES}


def test_the_script_has_every_stage_the_plan_promises():
    assert list(STAGES) == ["PREREQUISITES CHECK (read only)", "STAGE 0", "STAGE 1", "STAGE 2", "STAGE 2b", "STAGE 3", "STAGE 4", "STAGE 5",
                            "STAGE 6", "STAGE 7", "STAGE 8", "STAGE 8b", "STAGE 9", "STAGE 10"]


def test_every_delete_and_update_is_scoped_to_strk_test_rows():
    deletes = re.findall(r"DELETE FROM .*?(?=\$q\$|;)", SCRIPT, flags=re.S)
    assert len(deletes) == 14
    for d in deletes:
        assert "STRK-TEST-%" in d, d
    for u in re.findall(r"UPDATE public\.\w+.*?;", SCRIPT, flags=re.S):
        if u.startswith("UPDATE public.restaurant_master"):   # only the operator hint (comment / error text), never executed
            assert re.fullmatch(r"UPDATE public\.restaurant_master SET rest_id = ''?STRK01''? WHERE rest_ref = ''?STRK''? AND rest_id IS NULL;", u), u
            continue
        assert "order_number = v_no" in u or "dispatch_id = (SELECT dispatch_id FROM public.delivery_inflight WHERE order_number LIKE 'STRK-TEST-%'" in u, u
    assert not re.search(r"\b(TRUNCATE|DROP|ALTER)\b", re.sub(r"--.*", "", SCRIPT))


def test_prerequisite_and_view_stages_run(db):
    link(db)
    for name in ["PREREQUISITES CHECK (read only)", "STAGE 2", "STAGE 3", "STAGE 4", "STAGE 5"]:
        run(db, name)  # read-only selects: must not raise
    assert db.execute("SELECT count(*) FROM public.t_order_card_destinations(%s, 'STRK')", (BOT,)).fetchone()[0] == 1


def test_stage0_wipes_only_strk_test_rows_in_every_table(db):
    link(db)
    # one STRK-TEST order with everything hanging off it, one real order with the same shape
    for no, oid in (("STRK-TEST-111111", "TEST-111111"), ("ELAS-REAL-1", "REAL-1")):
        db.execute("INSERT INTO public.food_order (order_id, order_number, total_price) VALUES (%s, %s, 5)", (oid, no))
        db.execute("INSERT INTO public.order_item (order_id, product_name, quantity) VALUES (%s, 'x', 1)", (oid,))
        db.execute("INSERT INTO public.delivery_summary (order_number, town) VALUES (%s, 'dummy')", (no,))
        db.execute("INSERT INTO public.takeaway_summary (order_number, town) VALUES (%s, 'dummy')", (no + "-T",))
        db.execute("INSERT INTO public.delivery_detail (order_number, customer_id, vehicle_type, town, rider_payout, distance, status) "
                   "VALUES (%s, '1', 'bike', 'dummy', 1, 1, 'unassigned')", (no,))
        did = fetch_one(db, "INSERT INTO public.delivery_dispatch (order_number, rider_id, status) VALUES (%s, 'RIDER01', 'assigned') RETURNING dispatch_id", (no,))
        db.execute("INSERT INTO public.delivery_inflight (dispatch_id, order_number, rider_id) VALUES (%s, %s, 'RIDER01')", (did, no))
        db.execute("INSERT INTO public.rider_pickup_alert (dispatch_id, phase, audience, offset_minutes, order_number, rider_id) "
                   "VALUES (%s, 'awaiting_pickup', 'rider', -10, %s, 'RIDER01')", (did, no))
        eid = fetch_one(db, "INSERT INTO public.order_customer_event (order_number, event_key, event_type) VALUES (%s, 'k', 't') RETURNING id", (no,))
        sid = fetch_one(db, "INSERT INTO public.order_notification_subscription (order_number, channel) VALUES (%s, 'web_page') RETURNING id", (no,))
        db.execute("INSERT INTO public.notification_outbox (event_id, subscription_id) VALUES (%s, %s)", (eid, sid))
        db.execute("INSERT INTO public.t_order_alerts (order_number, order_type, rest_ref, offset_secs, n, of_n, due_at) VALUES (%s, 'delivery', 'STRK', 0, 1, 1, now())", (no,))
        db.execute("INSERT INTO public.t_sent_messages (bot_key, tcid, message_id, subject_type, subject_ref, kind) VALUES (%s, 9, %s, 'order', %s, 'receipt')",
                   (BOT, 100 + len(no), no))
    db.execute("INSERT INTO public.t_sent_messages (bot_key, tcid, message_id, subject_type, subject_ref, kind) VALUES (%s, 9, 7001, 'rest', 'STRK', 'notice')", (BOT,))
    db.execute("INSERT INTO public.t_sent_messages (bot_key, tcid, message_id, subject_type, subject_ref, kind) VALUES (%s, 9, 7002, 'rest', 'ELAS', 'notice')", (BOT,))
    before = counts(db)

    run(db, "STAGE 0")

    after = counts(db)
    for t in ("food_order", "order_item", "delivery_summary", "delivery_detail", "delivery_dispatch", "delivery_inflight",
              "rider_pickup_alert", "order_customer_event", "order_notification_subscription", "notification_outbox", "t_order_alerts"):
        assert after[t] == before[t] - 1, t   # exactly the STRK-TEST row went
    assert after["takeaway_summary"] == before["takeaway_summary"] - 1
    assert after["t_sent_messages"] == before["t_sent_messages"] - 2   # the receipt copy and the STRK feedback notice
    for t in ("restaurant_master", "rider_master", "t_invites", "ordelo_config"):
        assert after[t] == before[t], t
    left = {r[0] for r in db.execute("SELECT order_number FROM public.food_order").fetchall()}
    assert left == {"ELAS-REAL-1"}
    assert fetch_one(db, "SELECT count(*) FROM public.t_sent_messages WHERE subject_ref IN ('ELAS-REAL-1', 'ELAS')") == 2


def test_stage0_copies_the_linked_chat_to_strk_only_once(db):
    db.execute("INSERT INTO public.t_invites (rest_ref, phone_number, status, claimed_at, telegram_user_id, telegram_chat_id, telegram_first_name) "
               "VALUES ('ELAS', %s, 'claimed', now(), 111, 111, 'Lohith')", (ADMIN,))
    run(db, "STAGE 0")
    run(db, "STAGE 0")
    assert fetch_one(db, "SELECT count(*) FROM public.t_invites WHERE rest_ref = 'STRK' AND status = 'claimed'") == 1
    assert fetch_one(db, "SELECT count(*) FROM public.t_invites WHERE rest_ref = 'ELAS'") == 1


def test_stage0_works_when_the_optional_tables_do_not_exist(db):
    db.execute("DROP TABLE public.notification_outbox, public.order_notification_subscription, public.order_customer_event, public.rider_pickup_alert")
    run(db, "STAGE 0")  # the to_regclass guards skip them


def test_stage1_creates_the_complete_delivery_order(db):
    link(db)
    run(db, "STAGE 0")
    run(db, "STAGE 1")
    o = db.execute("SELECT order_number, town, restaurant_confirmation_status, status, rest_confirmation_code, customer_id, rest_ref, pickup_time "
                   "FROM public.delivery_summary").fetchone()
    assert o[0].startswith("STRK-TEST-") and o[1:] == ("dummy", "restaurant_unconfirmed", "restaurant_unconfirmed", 47, ADMIN, "STRK", None)
    f = db.execute("SELECT order_id, recipient, action, payment_mode, payment_status, origin_channel, notes, total_price, small_order_fee, thread_id "
                   "FROM public.food_order").fetchone()
    assert f == (o[0].split("-", 1)[1], ADMIN, "delivery", "test", "test_no_payment", "whatsapp",
                 "Please ring the bell twice (STRK test order)", 21.5, 1.0, "STRK-TEST-THREAD")
    items = db.execute("SELECT product_name, quantity, price, modifications FROM public.order_item ORDER BY ctid").fetchall()
    assert items == [("TEST3100", 1, 1.0, None), ("Chicken Shawarma", 2, 8.5, ["extra garlic sauce"]), ("Fries", 1, 3.5, None)]
    assert fetch_one(db, "SELECT count(*) FROM public.delivery_detail") == 0      # released only after the restaurant accepted
    assert fetch_one(db, "SELECT rest_id FROM public.delivery_summary") == "STRK01"   # the REAL restaurant's id: the webhooks look it up
    assert fetch_one(db, "SELECT count(*) FROM public.t_order_card_destinations(%s, 'STRK')", (BOT,)) == 1


def test_stage2b_releases_to_riders_only_after_accept_and_pickup(db):
    link(db)
    run(db, "STAGE 0")
    run(db, "STAGE 1")
    run(db, "STAGE 2b")
    assert fetch_one(db, "SELECT count(*) FROM public.delivery_detail") == 0      # still unconfirmed: nothing released
    db.execute("UPDATE public.delivery_summary SET restaurant_confirmation_status = 'restaurant_accept', status = 'unassigned', "
               "pickup_time = now() + interval '30 minutes'")
    run(db, "STAGE 2b")
    run(db, "STAGE 2b")                                                           # repeatable
    assert db.execute("SELECT town, vehicle_type, status FROM public.delivery_detail").fetchall() == [("dummy", "bike", "unassigned")]


@pytest.mark.parametrize("stage", ["STAGE 1", "STAGE 8", "STAGE 8b", "STAGE 9"])
def test_stages_refuse_when_the_strk_restaurant_row_is_missing(db, stage):
    db.execute("DELETE FROM public.restaurant_master WHERE rest_ref = 'STRK'")
    run(db, "STAGE 0")
    with pytest.raises(Exception, match="no restaurant_master row for rest_ref STRK"):
        run(db, stage)


def test_stage1_refuses_when_there_is_no_dummy_rider(db):
    db.execute("DELETE FROM public.rider_master")
    run(db, "STAGE 0")
    with pytest.raises(Exception, match="no in-shift rider in town dummy"):
        run(db, "STAGE 1")
    assert fetch_one(db, "SELECT count(*) FROM public.food_order") == 0


def test_rerun_is_clean_even_in_the_same_second(db):
    link(db)
    for _ in range(2):
        run(db, "STAGE 0")
        run(db, "STAGE 1")
    assert [fetch_one(db, f"SELECT count(*) FROM public.{t}") for t in ("delivery_summary", "food_order", "order_item", "delivery_detail")] == [1, 1, 3, 0]
    time.sleep(1.1)
    run(db, "STAGE 0")
    run(db, "STAGE 1")
    assert fetch_one(db, "SELECT count(*) FROM public.delivery_summary") == 1


def test_every_fake_order_is_dummy_town_with_the_test_item_and_test_payment_mode(db):
    link(db)
    run(db, "STAGE 0")
    run(db, "STAGE 1")
    time.sleep(1.1)
    run(db, "STAGE 8")
    time.sleep(1.1)
    run(db, "STAGE 8b")
    time.sleep(1.1)
    run(db, "STAGE 9")
    towns = [r[0] for r in db.execute("SELECT town FROM public.delivery_summary UNION ALL SELECT town FROM public.takeaway_summary "
                                      "UNION ALL SELECT town FROM public.delivery_detail").fetchall()]
    assert len(towns) == 4 and set(towns) == {"dummy"}   # stages 1 and 9 (delivery), 8 and 8b (takeaway); no rider job before STAGE 2b
    assert fetch_one(db, "SELECT count(*) FROM public.food_order") == 4
    assert db.execute("SELECT DISTINCT payment_mode FROM public.food_order").fetchall() == [("test",)]
    assert fetch_one(db, "SELECT count(*) FROM public.food_order f WHERE EXISTS (SELECT 1 FROM public.order_item i WHERE i.order_id = f.order_id AND i.product_name = 'TEST3100')") == 4
    assert fetch_one(db, "SELECT count(*) FROM public.food_order WHERE order_number NOT LIKE 'STRK-TEST-%%'") == 0


def test_takeaway_stages_set_the_payment_status_the_plan_chose(db):
    link(db)
    run(db, "STAGE 0")
    run(db, "STAGE 8")
    time.sleep(1.1)
    run(db, "STAGE 8b")
    rows = dict(db.execute("SELECT payment_status, action FROM public.food_order").fetchall())
    assert rows == {"test_no_payment": "takeaway", "pay_at_rest": "takeaway"}
    assert fetch_one(db, "SELECT count(*) FROM public.takeaway_summary WHERE status = 'restaurant_unconfirmed' AND pickup_time IS NULL") == 2
    assert fetch_one(db, "SELECT count(*) FROM public.delivery_detail") == 0   # a takeaway never creates a rider job


def test_stage9_order_is_old_enough_to_time_out_and_cannot_be_dispatched(db):
    link(db)
    run(db, "STAGE 0")
    run(db, "STAGE 9")
    assert fetch_one(db, "SELECT now() - dtts > interval '50 minutes' FROM public.delivery_summary") is True
    assert fetch_one(db, "SELECT count(*) FROM public.delivery_detail") == 0


def _accept_and_assign(db):
    """What the app, the dispatch jobs and the rider do between stages 2 and 3, done by hand."""
    no = fetch_one(db, "SELECT order_number FROM public.delivery_summary")
    db.execute("UPDATE public.delivery_summary SET restaurant_confirmation_status = 'restaurant_accept', status = 'assigned', "
               "pickup_time = now() + interval '20 minutes', restaurant_admin = %s", (ADMIN,))
    did = fetch_one(db, "INSERT INTO public.delivery_dispatch (order_number, rider_id, status) VALUES (%s, 'RIDER01', 'assigned') RETURNING dispatch_id", (no,))
    db.execute("INSERT INTO public.delivery_inflight (dispatch_id, order_number, rider_id) VALUES (%s, %s, 'RIDER01')", (did, no))
    return no, did


def test_rows_from_stage1_are_enough_for_the_real_receipt_functions(db):
    link(db)
    run(db, "STAGE 0")
    run(db, "STAGE 1")
    no, did = _accept_and_assign(db)
    snap = fetch_one(db, "SELECT public.t_receipt_snapshot(%s, %s, 'delivery', %s)", (BOT, no, did))
    f = snap["facts"]
    assert snap["status"].startswith("open@") and snap["dispatch_id"] == did and len(snap["destinations"]) == 1
    assert f["rest_code"] == 47 and f["notes"] == "Please ring the bell twice (STRK test order)" and f["small_order_fee"] == 1.0
    assert f["rider"] == {"id": "RIDER01", "name": "Sam"} and f["customer"]["phone"] == ADMIN and f["pay_at_restaurant"] is False
    assert [(i["qty"], i["name"], i["line_total"], i["mods"]) for i in f["items"]] == [
        (1, "TEST3100", 1.0, []), (2, "Chicken Shawarma", 17.0, ["extra garlic sauce"]), (1, "Fries", 3.5, [])]
    # stage 4 and stage 7a views / forced pickup behave
    assert fetch_one(db, "SELECT public.t_order_ready(%s, 111, %s, 'delivery')", (BOT, no))["result"] == "ok"
    run(db, "STAGE 4")
    assert fetch_one(db, "SELECT public.t_receipt_status(%s, 'delivery', %s)", (no, did)).startswith("ready@")
    run(db, "STAGE 7")
    assert fetch_one(db, "SELECT public.t_receipt_status(%s, 'delivery', %s)", (no, did)) == "picked_up"


def test_takeaway_pay_at_restaurant_row_draws_the_pay_line_data(db):
    link(db)
    run(db, "STAGE 0")
    run(db, "STAGE 8b")
    no = fetch_one(db, "SELECT order_number FROM public.takeaway_summary")
    db.execute("UPDATE public.takeaway_summary SET status = 'pickup_confirmed', pickup_time = now() + interval '20 minutes'")
    snap = fetch_one(db, "SELECT public.t_receipt_snapshot(%s, %s, 'takeaway', NULL)", (BOT, no))
    assert snap["facts"]["pay_at_restaurant"] is True and snap["facts"]["total"] == 21.5 and snap["status"].startswith("open@")
    assert fetch_one(db, "SELECT public.t_order_ready(%s, 111, %s, 'takeaway')", (BOT, no))["result"] == "ok"


def test_stage6_and_the_commented_stage7_use_the_real_functions():
    assert "public.dispatch_cancel_before_pickup(" in STAGES["STAGE 6"]
    assert "public.dispatch_complete_func(" in STAGES["STAGE 7"]
    assert "/customer-hooks/restaurant-feedback" in STAGES["STAGE 10"]


@pytest.mark.parametrize("stage", ["STAGE 1", "STAGE 8", "STAGE 8b", "STAGE 9"])
def test_stages_say_exactly_what_to_run_when_strk_has_no_rest_id(db, stage):
    db.execute("UPDATE public.restaurant_master SET rest_id = NULL WHERE rest_ref = 'STRK'")
    run(db, "STAGE 0")
    with pytest.raises(Exception, match="rest_id is NULL for STRK.*UPDATE public.restaurant_master SET rest_id"):
        run(db, stage)


def test_the_restaurant_master_update_exists_only_as_text_for_the_owner():
    executable = re.sub(r"--.*", "", SCRIPT)
    executable = re.sub(r"RAISE EXCEPTION '.*?';\n", "", executable, flags=re.S)
    assert "UPDATE public.restaurant_master" not in executable
