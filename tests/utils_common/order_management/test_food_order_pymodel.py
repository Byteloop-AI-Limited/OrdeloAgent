"""Tests for the FoodOrder Pydantic model and helper methods.

The DB classmethods and summary builders run against FakeSupabaseClient; pricing
and overwatch dependencies are patched at module boundaries.

Key Functions:
  - test_from_order_id_returns_model_without_pricing_update_when_final_value_exists
  - test_from_order_number_returns_none_for_missing_row
  - test_payment_uri_uses_test_url_for_overwatch_delivery_customer
  - test_rest_ref_derives_lowercase_prefix
  - test_update_final_order_value_in_db_updates_instance_fields
  - test_generate_order_summary_for_payment_intent_adds_nonzero_fees
  - test_generate_order_summary_for_payment_intent_can_exclude_fees
  - test_generate_order_summary_for_automatic_payment_returns_items_and_total
  - test_gen_capture_and_payment_intent_payloads
  - test_takeaway_capture_payload_uses_collection_product_items
"""

from __future__ import annotations

from utils_common.order_management.food_order_pymodel import FoodOrder
from tests.fixtures.fake_supabase import FakeSupabaseResponse


def _food_order_row(**overrides):
    row = {
        "order_id": "ABCD-1",
        "order_number": "ELAS-ABCD-1",
        "recipient": "447400000000",
        "notes": "Ring bell",
        "thread_id": "thread-1",
        "action": "delivery",
        "total_price": 20.0,
        "final_order_value": 25.5,
        "rest_cost": 18.0,
        "service_charge": 1.5,
        "delivery_fee": 3.0,
        "small_order_fee": 0.0,
        "commission_rate": 0.1,
        "payment_status": "requires_payment",
    }
    row.update(overrides)
    return row


def _food_order(**overrides) -> FoodOrder:
    return FoodOrder(**_food_order_row(**overrides))


def test_from_order_id_returns_model_without_pricing_update_when_final_value_exists(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="food_order",
        verb="select",
        response=FakeSupabaseResponse(data=[_food_order_row()]),
    )

    order = FoodOrder.from_order_id("ABCD-1")

    assert order is not None
    assert order.order_id == "ABCD-1"
    assert patch_supabase_client.calls[-1].filters["eq:order_id"] == "ABCD-1"


def test_from_order_number_returns_none_for_missing_row(patch_supabase_client) -> None:
    patch_supabase_client.register(table="food_order", verb="select", response=FakeSupabaseResponse(data=[]))

    assert FoodOrder.from_order_number("MISSING") is None


def test_payment_uri_uses_test_url_for_overwatch_delivery_customer(monkeypatch) -> None:
    import utils_common.order_management.food_order_pymodel as module

    monkeypatch.setattr(module, "get_overwatch_list", lambda: ["447400000000"])

    assert _food_order().payment_uri == "https://test.example.com/stripe-test/threads/thread-1/orders/ABCD-1/payment-url"
    assert _food_order(action="takeaway").payment_uri == "https://test.example.com/stripe/threads/thread-1/orders/ABCD-1/payment-url"


def test_rest_ref_derives_lowercase_prefix() -> None:
    assert _food_order(order_number="SFCS-XYZ-1").rest_ref == "sfcs"


def test_update_final_order_value_in_db_updates_instance_fields(monkeypatch, patch_supabase_client) -> None:
    order = _food_order(final_order_value=None, rest_cost=None, service_charge=None, delivery_fee=None)
    patch_supabase_client.register(
        table="customer_master",
        verb="select",
        response=FakeSupabaseResponse(data={"lat": 51.5, "lon": -0.12}),
    )
    patch_supabase_client.register(table="food_order", verb="update", response=FakeSupabaseResponse(data=[{"ok": True}]))
    monkeypatch.setattr(
        FoodOrder,
        "get_final_order_value",
        staticmethod(lambda **_: {
            "final_order_value": 26.5,
            "rest_cost": 19.0,
            "breakdown": {"service_charge": 1.5, "delivery_fee": 4.0, "small_order_fee": 2.0, "commission_rate": 0.1},
        }),
    )

    assert order.update_final_order_value_in_db() is True
    assert order.final_order_value == 26.5
    assert order.delivery_fee == 4.0


async def test_generate_order_summary_for_payment_intent_adds_nonzero_fees(patch_supabase_client) -> None:
    order = _food_order(small_order_fee=0.0)
    patch_supabase_client.register(
        table="order_item",
        verb="select",
        response=FakeSupabaseResponse(data=[{"product_name": "Burger", "quantity": 1, "price": 10.0, "modifications": []}]),
    )

    summary = await order.generate_order_summary_for_payment_intent()

    assert summary["items"][0]["product_name"] == "Burger"
    assert {item["product_name"] for item in summary["items"]} == {"Burger", "Service Charge", "Delivery Fee"}


async def test_generate_order_summary_for_payment_intent_can_exclude_fees(patch_supabase_client) -> None:
    order = _food_order()
    patch_supabase_client.register(
        table="order_item",
        verb="select",
        response=FakeSupabaseResponse(data=[{"product_name": "Burger", "quantity": 1, "price": 10.0, "modifications": []}]),
    )

    summary = await order.generate_order_summary_for_payment_intent(include_fee_items=False)

    assert summary["items"] == [{"product_name": "Burger", "quantity": 1, "price": 10.0, "modifications": []}]


async def test_generate_order_summary_for_automatic_payment_returns_items_and_total(patch_supabase_client) -> None:
    order = _food_order()
    patch_supabase_client.register(
        table="order_item",
        verb="select",
        response=FakeSupabaseResponse(data=[
            {"product_name": "Burger", "quantity": 2, "price": 5.0, "modifications": []},
            {"product_name": "Chips", "quantity": 1, "price": 3.0, "modifications": []},
        ]),
    )

    summary = await order.generate_order_summary_for_automatic_payment()

    assert summary["total"] == 13.0
    assert len(summary["items"]) == 2


async def test_gen_capture_and_payment_intent_payloads(patch_supabase_client) -> None:
    order = _food_order(small_order_fee=2.0)
    patch_supabase_client.register(
        table="order_item",
        verb="select",
        response=FakeSupabaseResponse(data=[{"product_name": "Burger", "quantity": 1, "price": 10.0, "modifications": []}]),
    )

    capture = await order.gen_capture_payload()
    intent = await order.gen_payment_intent_payload()

    assert capture["payment_mode"] == "capture"
    assert [item["product_name"] for item in capture["items"]] == ["Burger"]
    assert capture["rest_payout"] == 18.0
    assert capture["restRef"] == "elas"
    assert intent["currency"] == "GBP"
    assert intent["manual_mode_capture"] is True
    assert {item["product_name"] for item in intent["items"]} == {
        "Burger",
        "Service Charge",
        "Delivery Fee",
        "Small Order Fee",
    }


async def test_takeaway_capture_payload_uses_collection_product_items(
    patch_supabase_client,
) -> None:
    order = _food_order(
        action="takeaway",
        total_price=23.96,
        final_order_value=23.96,
        rest_cost=20.0,
    )
    item = {
        "product_name": "Matilda Cake",
        "quantity": 4,
        "price": 5.99,
        "modifications": [],
    }
    patch_supabase_client.register(
        table="order_item",
        verb="select",
        response=FakeSupabaseResponse(data=[item]),
    )

    capture = await order.gen_capture_payload()
    product_summary = await order.generate_product_order_summary()

    assert capture["action"] == "collection"
    assert capture["items"] == [item]
    assert product_summary["items"] == capture["items"]
    assert product_summary["total"] == 23.96
    assert capture["total_amount"] == 23.96
