"""Tests for high-level order service helpers.

Pricing HTTP is patched through a fake ``requests.post`` and DB persistence runs
against FakeSupabaseClient.

Key Functions:
  - test_call_pricing_service_adds_order_number_and_returns_json
  - test_call_pricing_service_returns_none_on_request_error
  - test_resolve_restaurant_coordinates_uses_explicit_or_rest_ref_lookup
  - test_get_min_order_value_for_location_returns_car_message
  - test_get_min_order_value_returns_minus_one_when_pricing_fails
  - test_create_order_with_items_success
  - test_create_order_with_items_rolls_back_when_order_items_insert_empty
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from utils_common.order_management import order_service
from utils_common.order_management.order_db_ops_new import OrderItem
from tests.fixtures.fake_supabase import FakeSupabaseResponse


class _Response:
    def __init__(self, json_data=None, raise_error=None):
        self._json_data = json_data or {}
        self._raise_error = raise_error

    def raise_for_status(self):
        if self._raise_error:
            raise self._raise_error

    def json(self):
        return self._json_data


def _items() -> list[OrderItem]:
    return [
        OrderItem(order_id="placeholder", sku="burger", quantity=2, price=5.0, product_name="Burger", modifications=["No onions"]),
        OrderItem(order_id="placeholder", sku="chips", quantity=1, price=3.0, product_name="Chips"),
    ]


def test_call_pricing_service_adds_order_number_and_returns_json(monkeypatch) -> None:
    post = MagicMock(return_value=_Response({"delivery_options": []}))
    monkeypatch.setattr(order_service.requests, "post", post)
    payload = {"total_food_value": 0}

    result = order_service._call_pricing_service(payload)

    assert result == {"delivery_options": []}
    assert "order_number" in payload
    post.assert_called_once()


def test_call_pricing_service_returns_none_on_request_error(monkeypatch) -> None:
    monkeypatch.setattr(order_service.requests, "post", MagicMock(side_effect=order_service.requests.exceptions.Timeout("timeout")))

    assert order_service._call_pricing_service({}) is None


def test_resolve_restaurant_coordinates_uses_explicit_or_rest_ref_lookup(patch_supabase_client) -> None:
    assert order_service._resolve_restaurant_coordinates(51.5, -0.12, None) == (51.5, -0.12)

    patch_supabase_client.register(
        table="restaurant_master",
        verb="select",
        response=FakeSupabaseResponse(data=[{"lat": "51.6", "lon": "-0.13"}]),
    )
    assert order_service._resolve_restaurant_coordinates(None, None, "elas") == (51.6, -0.13)

    patch_supabase_client.register(table="restaurant_master", verb="select", response=FakeSupabaseResponse(data=[]))
    with pytest.raises(ValueError, match="not found"):
        order_service._resolve_restaurant_coordinates(None, None, "missing")


def test_get_min_order_value_for_location_returns_car_message(monkeypatch) -> None:
    monkeypatch.setattr(
        order_service,
        "_call_pricing_service",
        lambda payload: {"delivery_options": [{"vehicle_type": "bike", "message": "bike"}, {"vehicle_type": "car", "message": "Min £20"}]},
    )

    assert order_service.get_min_order_value_for_location(51.5, -0.12, rest_lat=51.6, rest_lon=-0.13) == "Min £20"


def test_get_min_order_value_returns_minus_one_when_pricing_fails(monkeypatch) -> None:
    monkeypatch.setattr(order_service, "_call_pricing_service", lambda payload: None)

    assert order_service.get_min_order_value(51.5, -0.12, rest_lat=51.6, rest_lon=-0.13) == -1


async def test_create_order_with_items_success(monkeypatch, patch_supabase_client) -> None:
    monkeypatch.setattr(order_service, "create_order_reference", lambda recipient, order_dt: "ABCD")
    patch_supabase_client.register_rpc("get_next_daily_seq", FakeSupabaseResponse(data=9))
    patch_supabase_client.register(table="food_order", verb="insert", response=FakeSupabaseResponse(data=[{"ok": True}]))
    patch_supabase_client.register(table="order_item", verb="insert", response=FakeSupabaseResponse(data=[{"ok": True}]))

    result = await order_service.create_order_with_items("447448440754", "thread-1", _items(), "elas", "delivery", notes="note")

    assert result == {"success": True, "order_id": "ABCD-9", "order_number": "ELAS-ABCD-9"}
    food_order_call = next(c for c in patch_supabase_client.calls if c.table == "food_order" and c.verb == "insert")
    assert food_order_call.payload["total_price"] == 13.0
    assert food_order_call.payload["notes"] == "note"


async def test_create_order_with_items_rolls_back_when_order_items_insert_empty(monkeypatch, patch_supabase_client) -> None:
    monkeypatch.setattr(order_service, "create_order_reference", lambda recipient, order_dt: "ABCD")
    patch_supabase_client.register_rpc("get_next_daily_seq", FakeSupabaseResponse(data=9))
    patch_supabase_client.register(table="food_order", verb="insert", response=FakeSupabaseResponse(data=[{"ok": True}]))
    patch_supabase_client.register(table="order_item", verb="insert", response=FakeSupabaseResponse(data=[]))

    result = await order_service.create_order_with_items("447448440754", "thread-1", _items(), "elas", "delivery")

    assert result["success"] is False
    assert result["error"] == "No data returned from order_item insert operation"
    assert any(c.table == "food_order" and c.verb == "delete" for c in patch_supabase_client.calls)
