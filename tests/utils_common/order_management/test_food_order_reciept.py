"""Tests for WhatsApp food-order receipt formatting.

Covers item formatting, modification rendering, DB item fetch fallback, and
customer/restaurant receipt assembly from supplied model instances.

Key Functions:
  - test_format_order_item_lines_renders_modifications_under_parent_item
  - test_fetch_order_items_returns_rows_or_empty_on_failure
  - test_build_customer_receipt_includes_charges_total_and_notes
  - test_build_restaurant_receipt_uses_food_total_and_order_items_models
"""

from __future__ import annotations

from utils_common.order_management.food_order_pymodel import FoodOrder
from utils_common.order_management.food_order_reciept import (
    _fetch_order_items,
    _format_order_item_lines,
    build_wa_order_reciept_for_cust,
    build_wa_order_reciept_for_rest,
)
from utils_common.order_management.order_db_ops_new import OrderItem
from tests.fixtures.fake_supabase import FakeSupabaseResponse


def _food_order(**overrides) -> FoodOrder:
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
        "small_order_fee": 1.0,
        "commission_rate": 0.1,
        "payment_status": "requires_payment",
    }
    row.update(overrides)
    return FoodOrder(**row)


def test_format_order_item_lines_renders_modifications_under_parent_item() -> None:
    lines = _format_order_item_lines([
        {"quantity": 2, "product_name": "Burger", "price": 5.0, "modifications": ["No onions", "Extra cheese"]},
        {"quantity": 1, "product_name": "Fries", "price": 3.5, "modifications": "No salt"},
    ])

    assert lines == [
        "*• 2 × Burger  –  £10.00*",
        "   ↳ _No onions_",
        "   ↳ _Extra cheese_",
        "*• 1 × Fries  –  £3.50*",
        "   ↳ _No salt_",
    ]


def test_fetch_order_items_returns_rows_or_empty_on_failure(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="order_item",
        verb="select",
        response=FakeSupabaseResponse(data=[{"product_name": "Burger"}]),
    )
    assert _fetch_order_items("ABCD-1") == [{"product_name": "Burger"}]

    patch_supabase_client.register(table="order_item", verb="select", response=RuntimeError("boom"))
    assert _fetch_order_items("ABCD-1") == []


def test_build_customer_receipt_includes_charges_total_and_notes(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="order_item",
        verb="select",
        response=FakeSupabaseResponse(data=[{"quantity": 1, "product_name": "Burger", "price": 10.0, "modifications": []}]),
    )

    header, text = build_wa_order_reciept_for_cust(food_order=_food_order())

    assert header == "Order #ELAS-ABCD-1"
    assert "*• 1 × Burger  –  £10.00*" in text
    assert "Service charge: £1.50" in text
    assert "Delivery fee: £3.00" in text
    assert "Small order fee: £1.00" in text
    assert "*Total:* £25.50" in text
    assert "_Ring bell_" in text


def test_build_restaurant_receipt_uses_food_total_and_order_items_models() -> None:
    order_items = [
        OrderItem(
            order_id="ABCD-1",
            sku="burger",
            quantity=2,
            price=5.0,
            product_name="Burger",
            modifications=["No onions"],
        )
    ]

    header, text = build_wa_order_reciept_for_rest(
        food_order=_food_order(total_price=20.0, final_order_value=25.5),
        order_items=order_items,
    )

    assert header == "Order #ELAS-ABCD-1 (Kitchen)"
    assert "*Total:* £20.00" in text
    assert "Service charge" not in text
    assert "Delivery fee" not in text
    assert "   ↳ _No onions_" in text
