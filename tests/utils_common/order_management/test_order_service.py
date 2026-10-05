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
  - test_create_order_with_items_writes_web_origin_and_storefront
  - test_create_order_with_items_always_uses_one_transaction
  - test_create_order_with_items_retries_random_reference_on_duplicate
  - test_create_order_with_items_does_not_retry_phone_reference
  - test_create_order_with_items_rejects_unknown_origin
  - test_create_order_with_items_writes_test_payment_mode
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


@pytest.fixture(autouse=True)
def _no_subscription_db(monkeypatch):
    """Every new order now gets a notifier subscription; keep it off the real database."""
    from unittest.mock import AsyncMock
    from utils_common.notify import customer_notifier

    monkeypatch.setattr(customer_notifier, "create_origin_subscription", AsyncMock())


def _rpc_order(patch_supabase_client) -> dict:
    rpc = next(c for c in patch_supabase_client.rpc_calls if c.payload["name"] == "create_food_order_with_items")
    return rpc.payload["args"]["p_order"]


async def test_create_order_with_items_success(monkeypatch, patch_supabase_client) -> None:
    monkeypatch.setattr(order_service, "new_order_reference", lambda recipient, order_dt: "ABCD")
    patch_supabase_client.register_rpc("get_next_daily_seq", FakeSupabaseResponse(data=9))
    patch_supabase_client.register_rpc("create_food_order_with_items", FakeSupabaseResponse(data={"item_count": 1}))

    result = await order_service.create_order_with_items("447448440754", "thread-1", _items(), "elas", "delivery", notes="note")

    assert result == {"success": True, "order_id": "ABCD-9", "order_number": "ELAS-ABCD-9"}
    order = _rpc_order(patch_supabase_client)
    assert order["total_price"] == 13.0
    assert order["notes"] == "note"
    # WhatsApp orders leave the new columns to their defaults.
    assert "origin_channel" not in order
    assert "storefront" not in order


@pytest.mark.parametrize("origin", ["whatsapp", "web"])
async def test_notifier_subscription_created_after_success(monkeypatch, patch_supabase_client, origin):
    """R3.1: every restaurant, no rollout rows (SFCS was never in the pilot)."""
    from unittest.mock import AsyncMock
    from utils_common.notify import customer_notifier
    subscription = AsyncMock()
    monkeypatch.setattr(customer_notifier, "create_origin_subscription", subscription)
    monkeypatch.setattr(order_service, "new_order_reference", lambda *args: "ABCD")
    patch_supabase_client.register_rpc("get_next_daily_seq", FakeSupabaseResponse(data=9))
    patch_supabase_client.register_rpc("create_food_order_with_items", FakeSupabaseResponse(data={"item_count": 1}))
    recipient = "W7K2M9QX4TPA" if origin == "web" else "447400000000"
    result = await order_service.create_order_with_items(recipient, "thread-1", _items(), "SFCS", "delivery", origin_channel=origin)
    assert result["success"]
    subscription.assert_awaited_once_with("SFCS-ABCD-9")


async def test_create_order_with_items_writes_web_origin_and_storefront(monkeypatch, patch_supabase_client) -> None:
    monkeypatch.setattr(order_service, "new_order_reference", lambda recipient, order_dt: "QKZD")
    patch_supabase_client.register_rpc("get_next_daily_seq", FakeSupabaseResponse(data=31))
    patch_supabase_client.register_rpc("create_food_order_with_items", FakeSupabaseResponse(data={"item_count": 1}))

    result = await order_service.create_order_with_items(
        "W7K2M9QX4TPA", "WEB-1", _items(), "sfcs", "delivery", origin_channel="web", storefront="ordelo"
    )

    assert result == {"success": True, "order_id": "QKZD-31", "order_number": "SFCS-QKZD-31"}
    order = _rpc_order(patch_supabase_client)
    assert order["origin_channel"] == "web"
    assert order["storefront"] == "ordelo"
    assert order["recipient"] == "W7K2M9QX4TPA"


async def test_create_order_with_items_always_uses_one_transaction(monkeypatch, patch_supabase_client) -> None:
    monkeypatch.setattr(order_service, "new_order_reference", lambda recipient, order_dt: "ABCD")
    patch_supabase_client.register_rpc("get_next_daily_seq", FakeSupabaseResponse(data=9))
    patch_supabase_client.register_rpc("create_food_order_with_items", FakeSupabaseResponse(data={"item_count": 1}))

    result = await order_service.create_order_with_items("447448440754", "thread-1", _items(), "elas", "delivery")

    assert result == {"success": True, "order_id": "ABCD-9", "order_number": "ELAS-ABCD-9"}
    rpc = next(c for c in patch_supabase_client.rpc_calls if c.payload["name"] == "create_food_order_with_items")
    assert rpc.payload["args"]["p_order"]["order_id"] == "ABCD-9"
    assert rpc.payload["args"]["p_items"][0].keys() == {"product_name", "sku", "quantity", "price", "modifications"}
    assert not any(c.table in ("food_order", "order_item") for c in patch_supabase_client.calls)


async def test_create_order_with_items_retries_random_reference_on_duplicate(monkeypatch, patch_supabase_client) -> None:
    refs = iter(["AAAA", "BBBB"])
    monkeypatch.setattr(order_service, "new_order_reference", lambda recipient, order_dt: next(refs))
    patch_supabase_client.register_rpc("get_next_daily_seq", FakeSupabaseResponse(data=5))
    attempts = []

    def _rpc(call):
        attempts.append(call.payload["args"]["p_order"]["order_id"])
        if len(attempts) == 1:
            raise Exception('duplicate key value violates unique constraint "food_order_order_id_key"')
        return FakeSupabaseResponse(data={"item_count": 1})

    patch_supabase_client.register_rpc("create_food_order_with_items", _rpc)

    result = await order_service.create_order_with_items("W7K2M9QX4TPA", "WEB-1", _items(), "elas", "takeaway", origin_channel="web")

    assert attempts == ["AAAA-5", "BBBB-5"]
    assert result == {"success": True, "order_id": "BBBB-5", "order_number": "ELAS-BBBB-5"}


async def test_create_order_with_items_does_not_retry_phone_reference(monkeypatch, patch_supabase_client) -> None:
    monkeypatch.setattr(order_service, "new_order_reference", lambda recipient, order_dt: "ABCD")
    patch_supabase_client.register_rpc("get_next_daily_seq", FakeSupabaseResponse(data=9))
    patch_supabase_client.register_rpc(
        "create_food_order_with_items", Exception('duplicate key value violates unique constraint "food_order_order_id_key"')
    )

    result = await order_service.create_order_with_items("447448440754", "thread-1", _items(), "elas", "delivery")

    assert result["success"] is False
    assert "duplicate_order_id" not in result
    assert sum(1 for c in patch_supabase_client.rpc_calls if c.payload["name"] == "create_food_order_with_items") == 1


async def test_create_order_with_items_rejects_unknown_origin(patch_supabase_client) -> None:
    result = await order_service.create_order_with_items("447448440754", "thread-1", _items(), "elas", "delivery", origin_channel="sms")

    assert result["success"] is False
    assert patch_supabase_client.calls == []


async def test_create_order_with_items_writes_test_payment_mode(monkeypatch, patch_supabase_client) -> None:
    monkeypatch.setattr(order_service, "new_order_reference", lambda recipient, order_dt: "ABCD")
    patch_supabase_client.register_rpc("get_next_daily_seq", FakeSupabaseResponse(data=9))
    patch_supabase_client.register_rpc("create_food_order_with_items", FakeSupabaseResponse(data={"item_count": 1}))

    await order_service.create_order_with_items("447448440754", "thread-1", _items(), "elas", "takeaway", payment_mode="test")

    assert _rpc_order(patch_supabase_client)["payment_mode"] == "test"
