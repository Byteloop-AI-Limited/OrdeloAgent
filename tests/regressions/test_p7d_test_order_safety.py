"""Step 7d.1: why the STRK harness orders (ordelo_datamodels/misc_sql/test_restaurant_notices.sql) cannot cause a LIVE payment.

Every harness order carries an exact TEST3100 item, so food_order.payment_mode = 'test' (the isolated-database test of the
script proves the rows; create_food_order_with_items derives the mode). These offline tests prove the Python side:
  * payment_mode 'test' sends every payment-service request to ms_settings.stripe_url_test, never the live URL;
  * delivery capture / cancel on such an order fail softly (the test service has no such thread -> HTTP 4xx, caught, None);
  * takeaway 'test_no_payment' returns before ANY HTTP call (one overwatch reconciliation message);
  * takeaway 'pay_at_rest' makes exactly ONE request, a print-only job, to the TEST service;
  * generate_product_order_summary / gen_capture_payload read order_item only (no outside call).
respx raises on any request that has no registered route, so an unexpected host fails the test."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from config import ms_settings
from tests.fixtures.fake_supabase import FakeSupabaseResponse
from utils_common.order_management import food_order_pymodel
from utils_common.order_management.food_order_pymodel import FoodOrder
from watomation.routers import delivery_hooks, takeaway_hooks

TEST_BASE = ms_settings.stripe_url_test
LIVE_BASE = ms_settings.stripe_url
ITEMS = [
    {"product_name": "TEST3100", "quantity": 1, "price": 1.0, "modifications": None},
    {"product_name": "Chicken Shawarma", "quantity": 2, "price": 8.5, "modifications": ["extra garlic sauce"]},
]


def harness_order(action="delivery", payment_status="test_no_payment", mode="test") -> FoodOrder:
    return FoodOrder(
        order_id="TEST-123456", order_number="STRK-TEST-123456", recipient="447448440754", thread_id="STRK-TEST-THREAD",
        action=action, total_price=21.5, final_order_value=22.5, rest_cost=15.0, service_charge=0, delivery_fee=0,
        small_order_fee=1.0, payment_status=payment_status, payment_mode=mode, notes="STRK test order",
    )


@pytest.fixture
def order_items(monkeypatch, patch_supabase_client):
    patch_supabase_client.register(table="order_item", verb="select", response=FakeSupabaseResponse(data=ITEMS))
    monkeypatch.setattr(food_order_pymodel, "client_ordelo", patch_supabase_client)
    return patch_supabase_client


@pytest.fixture
def serve(monkeypatch):
    def _serve(order: FoodOrder):
        for module in (delivery_hooks, takeaway_hooks):
            monkeypatch.setattr(module.FoodOrder, "from_order_number", staticmethod(lambda **_: order))
    return _serve


@pytest.fixture
def alerts(monkeypatch):
    seen: list[str] = []

    async def _notify(*, log_msg: str) -> None:
        seen.append(log_msg)

    monkeypatch.setattr(takeaway_hooks, "notify_overwatch", _notify)
    return seen


def test_the_test_and_live_services_are_different_hosts():
    assert TEST_BASE != LIVE_BASE and not LIVE_BASE.startswith(TEST_BASE + "/")


def test_a_test_mode_order_can_only_address_the_test_service():
    uri = harness_order().payment_uri
    assert uri == f"{TEST_BASE}/threads/STRK-TEST-THREAD/orders/TEST-123456/payment-url"
    assert harness_order(mode="live").payment_uri.startswith(f"{LIVE_BASE}/threads/")


def test_an_order_without_a_recorded_mode_is_an_error_not_a_guess():
    with pytest.raises(ValueError, match="Payment environment unresolved"):
        harness_order(mode=None).payment_uri


@respx.mock
async def test_delivery_capture_on_a_harness_order_fails_softly_at_the_test_service(serve, order_items):
    order = harness_order()
    serve(order)
    route = respx.post(order.payment_uri).mock(return_value=httpx.Response(404, json={"error": "no such thread"}))
    assert await delivery_hooks.capture_delivery_payment(order.order_number, 47) is None
    assert len(route.calls) == 1
    body = json.loads(route.calls[0].request.content)
    assert body["payment_mode"] == "capture" and body["items"][0]["product_name"] == "TEST3100"


@respx.mock
async def test_delivery_cancel_on_a_harness_order_fails_softly_at_the_test_service(serve):
    order = harness_order()
    serve(order)
    route = respx.post(order.payment_uri).mock(return_value=httpx.Response(404, json={"error": "no such thread"}))
    assert await delivery_hooks.cancel_payment(order.order_number) is None
    assert len(route.calls) == 1 and json.loads(route.calls[0].request.content)["payment_mode"] == "cancel"


@respx.mock
async def test_a_connection_failure_to_the_payment_service_is_caught_too(serve, order_items):
    order = harness_order()
    serve(order)
    respx.post(order.payment_uri).mock(side_effect=httpx.ConnectError("refused"))
    assert await delivery_hooks.capture_delivery_payment(order.order_number, 47) is None


@respx.mock
async def test_takeaway_test_no_payment_makes_no_http_call_and_raises_one_reconciliation_message(serve, alerts):
    order = harness_order("takeaway", "test_no_payment")
    serve(order)
    assert await takeaway_hooks.capture_takeaway_payment(order.order_number) is None   # any HTTP call would raise in respx
    assert len(respx.calls) == 0 and len(alerts) == 1 and "STRK-TEST-123456" in alerts[0]


@respx.mock
async def test_takeaway_pay_at_rest_makes_exactly_one_print_only_request_to_the_test_service(serve, alerts, order_items):
    order = harness_order("takeaway", "pay_at_rest")
    serve(order)
    route = respx.post(order.payment_uri).mock(return_value=httpx.Response(200, json={"url": "https://example.test/print"}))
    assert await takeaway_hooks.capture_takeaway_payment(order.order_number) is None
    assert len(route.calls) == 1 and len(respx.calls) == 1 and alerts == []
    body = json.loads(route.calls[0].request.content)
    assert body["printonlyjob"] is True and body["manual_mode_capture"] is False and body["action"] == "collection"


async def test_building_the_payload_reads_the_database_only(order_items):
    order = harness_order()
    summary = await order.generate_product_order_summary()
    payload = await order.gen_capture_payload()
    assert summary["total"] == 18.0 and payload["items"] == ITEMS and payload["payment_mode"] == "capture"
    assert {c.table for c in order_items.calls} == {"order_item"}   # nothing but the order_item read
