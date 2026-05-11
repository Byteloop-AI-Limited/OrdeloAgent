"""Tests for order webhook router helpers.

Order hook callables are tested directly with patched service dependencies,
respx HTTP mocks, and fake Supabase clients to cover pricing lookup, order
creation, address capture, postcode validation, and active-thread proxying.

Key Functions:
  - test_get_min_order_value_validates_inputs_and_returns_service_value
  - test_get_min_order_value_by_postcode_resolves_addresses
  - test_create_order_returns_payment_url_for_delivery_and_takeaway
  - test_validate_postcode_returns_resolved_address
  - test_capture_address_upserts_customer_and_notifies_restaurant
  - test_get_active_thread_proxies_restaurant_response
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
import respx
from fastapi import HTTPException

from tests.fixtures.fake_supabase import FakeSupabaseResponse
from utils_common.order_management.order_db_ops_new import OrderItem
from watomation.routers import order_hooks


def _order_items() -> list[OrderItem]:
    return [OrderItem(order_id="placeholder", sku="burger", quantity=1, price=10.0, product_name="Burger")]


def _food_order(action: str = "delivery") -> SimpleNamespace:
    return SimpleNamespace(
        order_id="ABCD-1",
        order_number="ELAS-ABCD-1",
        recipient="447400000000",
        thread_id="thread-1",
        action=action,
        service_charge=1.0,
        delivery_fee=2.0,
        small_order_fee=0.0,
        notes="No onions",
    )


async def test_get_min_order_value_validates_inputs_and_returns_service_value(monkeypatch) -> None:
    with pytest.raises(HTTPException) as missing:
        await order_hooks.get_min_order_value(
            51.5,
            -0.1,
            restaurant_latitude=None,
            restaurant_longitude=None,
            rest_ref=None,
        )
    assert missing.value.status_code == 400

    with pytest.raises(HTTPException) as partial:
        await order_hooks.get_min_order_value(
            51.5,
            -0.1,
            restaurant_latitude=51.6,
            restaurant_longitude=None,
            rest_ref=None,
        )
    assert partial.value.status_code == 400

    monkeypatch.setattr(order_hooks, "fetch_min_order_value", lambda *args, **kwargs: 12.5)

    result = await order_hooks.get_min_order_value(
        51.5,
        -0.1,
        restaurant_latitude=51.6,
        restaurant_longitude=-0.2,
    )

    assert result == {"status": "ok", "min_order_value": 12.5, "source": "service"}


async def test_get_min_order_value_by_postcode_resolves_addresses(monkeypatch) -> None:
    addresses = {
        "CUST": SimpleNamespace(latitude=51.5, longitude=-0.1),
        "REST": SimpleNamespace(latitude=51.6, longitude=-0.2),
    }
    monkeypatch.setattr(order_hooks.address_resolver, "get_address_from_postcode", lambda postcode: addresses[postcode])
    monkeypatch.setattr(order_hooks, "fetch_min_order_value", lambda *args, **kwargs: 15.0)

    result = await order_hooks.get_min_order_value_by_postcode(
        "CUST",
        restaurant_postcode="REST",
        rest_ref=None,
    )

    assert result == {"status": "ok", "min_order_value": 15.0, "source": "service"}

    addresses["CUST"] = SimpleNamespace(latitude=None, longitude=None)
    with pytest.raises(HTTPException) as bad_customer:
        await order_hooks.get_min_order_value_by_postcode(
            "CUST",
            restaurant_postcode="REST",
            rest_ref=None,
        )
    assert bad_customer.value.status_code == 400


async def test_create_order_returns_payment_url_for_delivery_and_takeaway(monkeypatch) -> None:
    async def _create_order(**kwargs):
        return {"success": True, "order_id": "ABCD-1", "order_number": "ELAS-ABCD-1"}

    async def _delivery_url(food_order):
        return "https://pay.example.com/intent"

    async def _takeaway_url(food_order):
        return "https://pay.example.com/auto"

    monkeypatch.setattr(order_hooks, "create_order_with_items", _create_order)
    monkeypatch.setattr(order_hooks.FoodOrder, "from_order_id", staticmethod(lambda order_id: _food_order("delivery")))
    monkeypatch.setattr(order_hooks, "generate_payment_intent_url", _delivery_url)
    monkeypatch.setattr(order_hooks, "generate_automatic_payment_url", _takeaway_url)

    delivery = await order_hooks.create_order(
        "ELAS",
        order_hooks.CreateOrderRequest(recipient="447400000000", thread_id="thread-1", order_items=_order_items(), order_type="delivery", notes="No onions"),
    )
    assert delivery["payment_intent_url"] == "https://pay.example.com/intent"
    assert delivery["service_charge"] == 1.0

    monkeypatch.setattr(order_hooks.FoodOrder, "from_order_id", staticmethod(lambda order_id: _food_order("takeaway")))
    takeaway = await order_hooks.create_order(
        "ELAS",
        order_hooks.CreateOrderRequest(recipient="447400000000", thread_id="thread-1", order_items=_order_items(), order_type="takeaway"),
    )
    assert takeaway["payment_intent_url"] == "https://pay.example.com/auto"


async def test_validate_postcode_returns_resolved_address(monkeypatch) -> None:
    address = SimpleNamespace(postcode="BR6 6DN", city="London")
    monkeypatch.setattr(order_hooks.address_resolver, "get_address_from_postcode", lambda postcode: address)

    assert await order_hooks.validate_postcode("BR66DN") is address


@respx.mock
async def test_capture_address_upserts_customer_and_notifies_restaurant(monkeypatch, patch_supabase_client) -> None:
    async def _webhook(rest_ref, webhook_type):
        return "https://rest.example.com/address-update"

    calls = []
    monkeypatch.setattr(order_hooks, "get_restaurant_webhook_url_async", _webhook)
    monkeypatch.setattr(order_hooks.CustRestMap, "upsert", staticmethod(lambda **kwargs: calls.append(kwargs)))
    route = respx.post("https://rest.example.com/address-update/447400000000").mock(return_value=httpx.Response(200, json={"ok": True}))
    request = order_hooks.CaptureAddressRequest(
        recipient="447400000000",
        rest_ref="ELAS",
        house_number="1",
        street_name="High Street",
        city="London",
        postcode="BR6 6DN",
        latitude=51.5,
        longitude=-0.1,
    )

    assert await order_hooks.capture_address(request) == {"success": True}
    assert patch_supabase_client.calls[-1].table == "customer_master"
    assert patch_supabase_client.calls[-1].verb == "upsert"
    assert calls == [{"cust_id": "447400000000", "rest_ref": "ELAS", "has_consent": False}]
    assert route.called


@respx.mock
async def test_get_active_thread_proxies_restaurant_response(monkeypatch) -> None:
    async def _webhook(rest_ref, webhook_type):
        return "https://rest.example.com/get-active-thread"

    monkeypatch.setattr(order_hooks, "get_restaurant_webhook_url_async", _webhook)
    respx.get("https://rest.example.com/get-active-thread/ELAS/447400000000").mock(
        return_value=httpx.Response(200, json={"thread_id": "thread-1"})
    )

    response = await order_hooks.get_active_thread("ELAS", "447400000000")

    assert response.status_code == 200
    assert response.body == b'{"thread_id":"thread-1"}'
