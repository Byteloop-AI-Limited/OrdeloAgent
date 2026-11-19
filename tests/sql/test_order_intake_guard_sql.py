"""Hidden menu items and the new-order guard on the isolated DB.

ordering/menu_item_visibility.sql (key rule, dashboard list/hide/show, audit) and ordering/order_intake_guard.sql through the
REAL create_food_order_with_items(): refuses with P0C01 / P0C02 only on a positive decision, writes nothing when it refuses,
and creates the order exactly as before otherwise.
"""

from __future__ import annotations

import json

import psycopg
import pytest

from .conftest import fetch_one, sql_path

pytestmark = pytest.mark.usefixtures("sql_env")

ADA = "447700900961"
H = {c: c * 64 for c in "abcdef"}
UA = "9" * 64
WEEK = {d: [["00:00", "24:00"]] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


@pytest.fixture(autouse=True)
def setup(db):
    # create_food_order_with_items writes these live columns; the minimal schema only has some of them
    for col in ("seq_id integer", "thread_id text", "storefront text", "payment_mode text", "idempotency_key text"):
        db.execute(f"ALTER TABLE public.food_order ADD COLUMN IF NOT EXISTS {col}")
    db.execute("ALTER TABLE public.order_item ADD COLUMN IF NOT EXISTS sku text")
    db.execute(sql_path("create_food_order_with_items.sql").read_text())
    db.execute("CREATE TABLE IF NOT EXISTS public.gard_menu (id bigint, title text, category text, availability text, price numeric)")

    def wipe():
        db.execute("DELETE FROM public.order_item WHERE order_id LIKE 'GARD-%'")
        db.execute("DELETE FROM public.food_order WHERE order_id LIKE 'GARD-%'")
        db.execute("DELETE FROM public.menu_item_hidden WHERE rest_ref = 'GARD'")
        db.execute("DELETE FROM public.restaurant_settings_audit WHERE rest_ref = 'GARD'")
        db.execute("DELETE FROM public.auth_sessions WHERE principal_id = %s", (ADA,))
        db.execute("DELETE FROM public.restaurant_master WHERE rest_ref = 'GARD'")
        db.execute("DELETE FROM public.gard_menu")
    wipe()
    db.execute("INSERT INTO public.restaurant_master (rest_ref, rest_name, admins, service_hours_json) VALUES ('GARD', 'Guard', %s, %s)",
               ([ADA], json.dumps(WEEK)))
    db.execute("INSERT INTO public.gard_menu VALUES (1, 'Chicken  Biryani', 'Mains', 'available', 9), (2, 'Naan', 'Sides', 'out_of_stock', 2),"
               " (3, 'chicken biryani', 'Mains', 'available', 10), (4, 'Lassi', 'Drinks', 'available', 3)")
    yield
    wipe()


def session(db):
    db.execute("INSERT INTO public.auth_sessions (role, principal_id, scope_ref, wa_number, token_hash, expires_at)"
               " VALUES ('rest_admin', %s, 'GARD', %s, %s, now() + interval '30 minutes')", (ADA, ADA, H["a"]))
    return fetch_one(db, "SELECT public.admin_dashboard_activate('rest_admin', %s, %s, %s, NULL)", (H["a"], H["c"], UA))["session_id"]


def order(db, n, items):
    return fetch_one(db, "SELECT public.create_food_order_with_items(%s::jsonb, %s::jsonb)",
                     (json.dumps({"order_id": f"GARD-{n}", "order_number": f"GARD-X-{n}", "seq_id": n, "recipient": "447700900001",
                                  "action": "delivery", "total_price": 10}),
                      json.dumps([{"product_name": t, "sku": None, "quantity": 1, "price": 9} for t in items])))




@pytest.mark.parametrize("title, key", [("Chicken  Biryani", "chicken biryani"), ("  NAAN ", "naan"), ("", None), (None, None)])
def test_item_key_normalises_titles(db, title, key):
    assert fetch_one(db, "SELECT public.menu_item_key(%s)", (title,)) == key


def test_list_hide_show_and_audit(db):
    sid = session(db)
    out = fetch_one(db, "SELECT public.rest_admin_menu_list(%s, NULL)", (sid,))
    assert out["result"] == "ok" and [i["key"] for i in out["items"]] == ["lassi", "chicken biryani", "naan"]  # by category; duplicates merged
    assert fetch_one(db, "SELECT public.rest_admin_menu_set_hidden(%s, %s, true)", (sid, ["Naan", "Chicken Biryani"]))["changed"] == 2
    assert fetch_one(db, "SELECT public.rest_admin_menu_set_hidden(%s, %s, true)", (sid, ["naan"]))["changed"] == 0  # idempotent
    assert fetch_one(db, "SELECT public.menu_hidden_keys('gard')") == ["chicken biryani", "naan"]
    listed = fetch_one(db, "SELECT public.rest_admin_menu_list(%s, 'naa')", (sid,))["items"]
    assert listed == [{"title": "Naan", "category": "Sides", "availability": "out_of_stock", "key": "naan", "hidden": True}]
    assert fetch_one(db, "SELECT public.rest_admin_menu_set_hidden(%s, %s, false)", (sid, ["naan"]))["changed"] == 1
    assert fetch_one(db, "SELECT availability FROM public.gard_menu WHERE title = 'Naan'") == "out_of_stock"  # stock untouched
    assert db.execute("SELECT setting, setting_key, new_value FROM public.restaurant_settings_audit WHERE rest_ref = 'GARD'"
                      " ORDER BY id").fetchall() == [("menu_hidden", "chicken biryani", True), ("menu_hidden", "naan", True),
                                                     ("menu_hidden", "naan", None)]


def test_hide_refuses_titles_not_on_the_menu_and_bad_input(db):
    sid = session(db)
    assert fetch_one(db, "SELECT public.rest_admin_menu_set_hidden(%s, %s, true)", (sid, ["Pizza"])) == {"result": "bad_items"}
    assert fetch_one(db, "SELECT public.rest_admin_menu_set_hidden(%s, %s, true)", (sid, [])) == {"result": "bad_items"}


def test_a_menu_refresh_keeps_the_hidden_state(db):
    sid = session(db)
    fetch_one(db, "SELECT public.rest_admin_menu_set_hidden(%s, %s, true)", (sid, ["Lassi"]))
    db.execute("DELETE FROM public.gard_menu")
    db.execute("INSERT INTO public.gard_menu VALUES (9, 'LASSI', 'Drinks', 'available', 3)")  # bulk-replaced menu
    assert fetch_one(db, "SELECT public.rest_admin_menu_list(%s, NULL)", (sid,))["items"][0]["hidden"] is True




# ---- the guard through the real create_food_order_with_items ----------------------------------------------------------
def test_orders_are_created_as_before_without_overrides_or_hidden_items(db):
    out = order(db, 1, ["Chicken Biryani", "Naan"])
    assert out["item_count"] == 2 and out["order"]["payment_mode"] == "live"


def test_hidden_item_refuses_the_order_and_writes_nothing(db):
    sid = session(db)
    fetch_one(db, "SELECT public.rest_admin_menu_set_hidden(%s, %s, true)", (sid, ["Naan"]))
    with pytest.raises(psycopg.Error) as e:
        order(db, 2, ["Chicken Biryani", " naan "])
    assert e.value.sqlstate == "P0C02"
    assert json.loads(e.value.diag.message_detail) == {"result": "hidden_items", "hidden": [" naan "]}
    assert fetch_one(db, "SELECT count(*) FROM public.food_order WHERE order_id = 'GARD-2'") == 0
    assert order(db, 3, ["Chicken Biryani"])["item_count"] == 1  # other items still sell


def test_closed_date_refuses_the_order(db):
    today = fetch_one(db, "SELECT to_char(now() AT TIME ZONE 'Europe/London', 'YYYY-MM-DD')")
    db.execute("UPDATE public.restaurant_master SET service_hours_json = %s WHERE rest_ref = 'GARD'",
               (json.dumps({**WEEK, "dates": {today: [["00:00", "00:01"]]}}),))
    with pytest.raises(psycopg.Error) as e:
        order(db, 4, ["Lassi"])
    assert e.value.sqlstate == "P0C01"
    assert fetch_one(db, "SELECT count(*) FROM public.food_order WHERE order_id = 'GARD-4'") == 0


def test_guard_errors_and_unknown_restaurants_never_block(db):
    assert fetch_one(db, "SELECT public.order_intake_block('NOPE', now(), '[{\"product_name\":\"x\"}]'::jsonb)") == {"result": "ok"}
    assert fetch_one(db, "SELECT public.order_intake_block(NULL, now(), NULL)") == {"result": "ok"}
    db.execute("UPDATE public.restaurant_master SET service_hours_json = '{\"dates\": \"garbage\"}' WHERE rest_ref = 'GARD'")
    assert order(db, 5, ["Lassi"])["item_count"] == 1
