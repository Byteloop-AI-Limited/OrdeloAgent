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


@pytest.fixture(autouse=True)
def _no_test_restaurants(monkeypatch):
    """Payment-mode config boundary: no test restaurants, no overwatch numbers."""
    from utils_common.payment_ms import payment_mode

    async def _csv(key, **kwargs):
        return frozenset()

    monkeypatch.setattr(payment_mode, "config_csv", _csv)
    monkeypatch.setattr(payment_mode, "get_overwatch_list", lambda: [])


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
    payment_builders_called: list[str] = []

    async def _create_order(**kwargs):
        return {"success": True, "order_id": "ABCD-1", "order_number": "ELAS-ABCD-1"}

    async def _delivery_url(food_order):
        payment_builders_called.append("delivery")
        return "https://pay.example.com/intent"

    async def _takeaway_url(food_order):
        payment_builders_called.append("takeaway")
        return "https://pay.example.com/manual"

    monkeypatch.setattr(order_hooks, "create_order_with_items", _create_order)
    monkeypatch.setattr(order_hooks.FoodOrder, "from_order_id", staticmethod(lambda order_id: _food_order("delivery")))
    monkeypatch.setattr(order_hooks, "generate_payment_intent_url", _delivery_url)
    monkeypatch.setattr(order_hooks, "generate_takeaway_manual_payment_url", _takeaway_url)

    delivery = await order_hooks.create_order(
        "ELAS",
        order_hooks.CreateOrderRequest(recipient="447400000000", thread_id="thread-1", order_items=_order_items(), order_type="delivery", notes="No onions"),
    )
    assert delivery["payment_intent_url"] == "https://pay.example.com/intent"
    assert delivery["service_charge"] == 1.0
    assert payment_builders_called == ["delivery"]

    monkeypatch.setattr(order_hooks.FoodOrder, "from_order_id", staticmethod(lambda order_id: _food_order("takeaway")))
    takeaway = await order_hooks.create_order(
        "ELAS",
        order_hooks.CreateOrderRequest(recipient="447400000000", thread_id="thread-1", order_items=_order_items(), order_type="takeaway"),
    )
    assert takeaway["payment_intent_url"] == "https://pay.example.com/manual"
    assert payment_builders_called == ["delivery", "takeaway"]


async def test_validate_postcode_returns_resolved_address(monkeypatch) -> None:
    address = SimpleNamespace(postcode="BR6 6DN", city="London")
    monkeypatch.setattr(order_hooks.address_resolver, "get_address_from_postcode", lambda postcode: address)

    assert await order_hooks.validate_postcode("BR66DN") is address


@respx.mock
async def test_capture_address_upserts_customer_and_notifies_restaurant(monkeypatch, patch_supabase_client, inline_notifier) -> None:
    async def _webhook(rest_ref, webhook_type):
        return "https://rest.example.com/address-update"

    calls = []
    inline_notifier.webhook = _webhook
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



async def test_create_order_passes_origin_and_raises_before_reading_failed_order(monkeypatch) -> None:
    received = {}

    async def _create_order(**kwargs):
        received.update(kwargs)
        return {"success": False, "error": "Failed to create order", "details": "boom"}

    def _from_order_id(order_id):
        raise AssertionError("must not read the order when creation failed (F3)")

    monkeypatch.setattr(order_hooks, "create_order_with_items", _create_order)
    monkeypatch.setattr(order_hooks.FoodOrder, "from_order_id", staticmethod(_from_order_id))

    with pytest.raises(HTTPException) as failed:
        await order_hooks.create_order(
            "SFCS",
            order_hooks.CreateOrderRequest(
                recipient="W7K2M9QX4TPA", thread_id="WEB-1", order_items=_order_items(),
                order_type="delivery", origin_channel="web", storefront="ordelo",
            ),
        )
    assert failed.value.status_code == 400
    assert received["origin_channel"] == "web" and received["storefront"] == "ordelo"
    assert order_hooks.CreateOrderRequest(
        recipient="447400000000", thread_id="t", order_items=_order_items(), order_type="takeaway"
    ).origin_channel == "whatsapp"


@respx.mock
async def test_capture_address_skips_restaurant_app_for_web_customer_key(monkeypatch, patch_supabase_client) -> None:
    async def _webhook(rest_ref, webhook_type):
        raise AssertionError("restaurant app must not be called for a W-id (ADR-0003)")

    monkeypatch.setattr(order_hooks, "get_restaurant_webhook_url_async", _webhook)
    monkeypatch.setattr(order_hooks.CustRestMap, "upsert", staticmethod(lambda **kwargs: None))
    request = order_hooks.CaptureAddressRequest(
        recipient="W7K2M9QX4TPA", rest_ref="SFCS", house_number="1", street_name="High Street",
        city="Salisbury", postcode="SP1 2AB", latitude=51.07, longitude=-1.79,
    )

    assert await order_hooks.capture_address(request) == {"success": True}
    upsert = next(c for c in patch_supabase_client.calls if c.table == "customer_master")
    assert upsert.payload["cust_id"] == "W7K2M9QX4TPA" and upsert.payload["cust_name"] == "W7K2M9QX4TPA"



# --- R3.1 (D35): the test restaurant list is the only payment switch ---------------------------

def _payment_config(monkeypatch, *, test_refs=frozenset({"BNAT"}), overwatch=("447400000000",)):
    from utils_common.payment_ms import payment_mode

    async def _csv(key, **kwargs):
        assert key == "TEST_PAYMENT_REST_REFS"
        return frozenset(test_refs)

    monkeypatch.setattr(payment_mode, "config_csv", _csv)
    monkeypatch.setattr(payment_mode, "get_overwatch_list", lambda: list(overwatch))


def _create_order_spy(monkeypatch, order_number):
    received = {}

    async def _create_order(**kwargs):
        received.update(kwargs)
        return {"success": True, "order_id": "ABCD-1", "order_number": order_number}

    async def _url(food_order):
        return "https://pay.example.com/intent"

    def _from_order_id(order_id):
        food_order = _food_order("delivery")
        food_order.payment_mode = received.get("payment_mode")
        food_order.uses_test_payment = food_order.payment_mode == "test"
        return food_order

    monkeypatch.setattr(order_hooks, "create_order_with_items", _create_order)
    monkeypatch.setattr(order_hooks.FoodOrder, "from_order_id", staticmethod(_from_order_id))
    monkeypatch.setattr(order_hooks, "generate_payment_intent_url", _url)
    return received


async def test_test_restaurant_order_is_test_without_asking(monkeypatch) -> None:
    _payment_config(monkeypatch)
    received = _create_order_spy(monkeypatch, "BNAT-ABCD-1")

    result = await order_hooks.create_order(
        "BNAT",
        order_hooks.CreateOrderRequest(recipient="447411111111", thread_id="t", order_items=_order_items(), order_type="delivery"),
    )

    assert received["payment_mode"] == "test"
    assert result["payment_mode"] == "test"


async def test_live_restaurant_is_live_unless_overwatch_asks(monkeypatch) -> None:
    _payment_config(monkeypatch)
    received = _create_order_spy(monkeypatch, "ELAS-ABCD-1")

    customer = await order_hooks.create_order(
        "ELAS",
        order_hooks.CreateOrderRequest(recipient="447411111111", thread_id="t", order_items=_order_items(),
                                       order_type="delivery", test_payment=True),
    )
    assert received["payment_mode"] is None and customer["payment_mode"] == "live"

    overwatch = await order_hooks.create_order(
        "ELAS",
        order_hooks.CreateOrderRequest(recipient="447400000000", thread_id="t", order_items=_order_items(),
                                       order_type="delivery", test_payment=True),
    )
    assert received["payment_mode"] == "test" and overwatch["payment_mode"] == "test"


@respx.mock
async def test_capture_address_succeeds_when_restaurant_app_is_down(monkeypatch, patch_supabase_client, inline_notifier) -> None:
    """The address is saved even if the restaurant app rejects the notice."""
    async def _webhook(rest_ref, webhook_type):
        return "https://rest.example.com/address-update"

    inline_notifier.webhook = _webhook
    monkeypatch.setattr(order_hooks.CustRestMap, "upsert", staticmethod(lambda **kwargs: None))
    respx.post("https://rest.example.com/address-update/447400000000").mock(return_value=httpx.Response(503))
    request = order_hooks.CaptureAddressRequest(
        recipient="447400000000", rest_ref="SFCS", house_number="1", street_name="High Street",
        city="Salisbury", postcode="SP1 2AB", latitude=51.07, longitude=-1.79,
    )

    assert await order_hooks.capture_address(request) == {"success": True}
