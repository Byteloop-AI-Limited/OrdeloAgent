"""Tests for payment webhook router helpers.

Payment hooks are invoked directly with fake request/background objects,
Supabase responses, and respx HTTP mocks to verify payment-complete fan-out,
summary initialization scheduling, and pay-at-restaurant validation.

Key Functions:
  - test_handle_payment_complete_posts_restaurant_webhook_and_swallows_http_errors
  - test_pay_at_restaurant_validates_action_and_schedules_takeaway
  - test_inbox_applies_once_and_skips_restaurant_app_for_web
  - test_inbox_duplicate_rejected_unknown_and_ignored_have_no_side_effects
  - test_test_replay_route_is_gone
  - test_init_reconciler_alerts_overwatch
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi import HTTPException

from tests.fixtures.fake_supabase import FakeSupabaseResponse
from watomation.routers import payment_hooks


class _FakeBackgroundTasks:
    def __init__(self) -> None:
        self.tasks = []

    def add_task(self, func, *args, **kwargs):
        self.tasks.append({"func": func, "args": args, "kwargs": kwargs})


class _FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


@pytest.fixture(autouse=True)
def _no_late_payment_lookup(monkeypatch):
    """The late-payment guard reads food_order; these orders aren't late web orders."""
    from unittest.mock import AsyncMock
    from utils_common.web_ordering import lifecycle

    monkeypatch.setattr(lifecycle, "one", AsyncMock(return_value=None))


def _food_order_row(action="delivery") -> dict:
    return {
        "order_id": "ABCD-1",
        "order_number": "ELAS-ABCD-1",
        "recipient": "447400000000",
        "thread_id": "thread-1",
        "action": action,
        "total_price": 20.0,
        "payment_status": "requires_payment",
    }


@respx.mock
async def test_handle_payment_complete_posts_restaurant_webhook_and_swallows_http_errors(monkeypatch, inline_notifier) -> None:
    async def _webhook(rest_ref, webhook_type):
        return "https://rest.example.com/payment-complete"

    inline_notifier.webhook = _webhook
    route = respx.post("https://rest.example.com/payment-complete/447400000000/thread-1").mock(return_value=httpx.Response(200, json={"ok": True}))
    food_order = payment_hooks.FoodOrder(**_food_order_row())

    assert await payment_hooks.handle_payment_complete(food_order) == {"success": "success"}
    assert route.called

    respx.post("https://rest.example.com/payment-complete/447400000000/thread-1").mock(return_value=httpx.Response(500, json={"error": "down"}))
    assert await payment_hooks.handle_payment_complete(food_order) == {"success": "success"}
    assert [status for _, status, _ in inline_notifier.finished] == ["sent", "failed"]


async def test_pay_at_restaurant_validates_action_and_schedules_takeaway(patch_supabase_client) -> None:
    request = payment_hooks.PayAtRest(
        recipient="447400000000",
        thread_id="thread-1",
        order_id="ELAS-ABCD-1",
        order_items=[],
        order_type="delivery",
    )
    with pytest.raises(HTTPException) as invalid:
        await payment_hooks.pay_at_restaurant("ELAS", request, _FakeBackgroundTasks())
    assert invalid.value.status_code == 400

    request.order_type = "takeaway"
    patch_supabase_client.register(table="food_order", verb="update", response=FakeSupabaseResponse(data=[]))
    with pytest.raises(HTTPException) as missing:
        await payment_hooks.pay_at_restaurant("ELAS", request, _FakeBackgroundTasks())
    assert missing.value.status_code == 404

    patch_supabase_client.register(table="food_order", verb="update", response=FakeSupabaseResponse(data=[_food_order_row("takeaway")]))
    bg = _FakeBackgroundTasks()
    result = await payment_hooks.pay_at_restaurant("ELAS", request, bg)
    assert result == {"status": "success", "order_number": "ELAS-ABCD-1"}
    assert [task["func"] for task in bg.tasks] == [payment_hooks.handle_payment_complete, payment_hooks.init_takeaway_summary]


def _web_row(action="delivery") -> dict:
    return _food_order_row(action) | {
        "order_id": "QKZD-31",
        "order_number": "SFCS-QKZD-31",
        "recipient": "W7K2M9QX4TPA",
        "thread_id": "WEB-1",
        "origin_channel": "web",
        "storefront": "ordelo",
    }


def _stripe_body(order_id="QKZD-31", event_id="evt_1", event_type="checkout.session.completed") -> dict:
    return {"id": event_id, "type": event_type, "data": {"object": {"id": "cs_1", "metadata": {"orderID": order_id}}}}


async def test_notifier_publishes_web_authorisation_once(patch_supabase_client):
    web = _web_row() | {"order_number": "BNAT-QKZD-31"}
    patch_supabase_client.register_rpc("record_payment_authorised", FakeSupabaseResponse(data={"outcome": "applied", "order": web}))
    bg = _FakeBackgroundTasks()
    await payment_hooks.payment_complete_path(_FakeRequest(_stripe_body()), bg)
    assert bg.tasks[0]["func"] is payment_hooks.handle_payment_complete
    assert bg.tasks[0]["args"][0].order_number == "BNAT-QKZD-31"
    assert bg.tasks[-1]["func"] is payment_hooks.init_delivery_summary
    patch_supabase_client.register_rpc("record_payment_authorised", FakeSupabaseResponse(data={"outcome": "duplicate"}))
    replay = _FakeBackgroundTasks()
    await payment_hooks.payment_complete_path(_FakeRequest(_stripe_body()), replay)
    assert replay.tasks == []


async def test_inbox_applies_once_and_skips_restaurant_app_for_web(patch_supabase_client, feature_flags) -> None:
    patch_supabase_client.register_rpc(
        "record_payment_authorised", FakeSupabaseResponse(data={"outcome": "applied", "order": _food_order_row("takeaway")})
    )
    bg = _FakeBackgroundTasks()
    result = await payment_hooks.payment_complete_path(_FakeRequest(_stripe_body("ABCD-1")), bg)
    assert result == {"success": "success", "outcome": "applied"}
    assert [task["func"] for task in bg.tasks] == [payment_hooks.handle_payment_complete, payment_hooks.init_takeaway_summary]
    assert not any(c.table == "food_order" for c in patch_supabase_client.calls)

    patch_supabase_client.register_rpc(
        "record_payment_authorised", FakeSupabaseResponse(data={"outcome": "applied", "order": _web_row("delivery")})
    )
    bg = _FakeBackgroundTasks()
    await payment_hooks.payment_complete_path(_FakeRequest(_stripe_body()), bg)
    from utils_common.web_ordering.common import query
    # Web: the customer event (routed to the order page), closing the web thread, then summary init.
    assert [task["func"] for task in bg.tasks] == [payment_hooks.handle_payment_complete, query, payment_hooks.init_delivery_summary]


@pytest.mark.parametrize(
    "rpc_data, body, expected",
    [
        ({"outcome": "duplicate"}, _stripe_body(), "duplicate"),
        ({"outcome": "rejected_state", "payment_status": "requires_capture"}, _stripe_body(), "rejected_state"),
        ({"outcome": "unknown_order"}, _stripe_body("NOPE-1"), "unknown_order"),
        (None, _stripe_body(event_type="payment_intent.created"), "ignored"),
        (None, {"data": {"object": {"metadata": {}}}}, "invalid"),
    ],
)
async def test_inbox_duplicate_rejected_unknown_and_ignored_have_no_side_effects(
    patch_supabase_client, feature_flags, rpc_data, body, expected
) -> None:
    if rpc_data is not None:
        patch_supabase_client.register_rpc("record_payment_authorised", FakeSupabaseResponse(data=rpc_data))
    bg = _FakeBackgroundTasks()

    result = await payment_hooks.payment_complete_path(_FakeRequest(body), bg)

    assert result == {"success": "success", "outcome": expected}
    assert bg.tasks == []
    if rpc_data is None:
        assert patch_supabase_client.rpc_calls == []


def test_test_replay_route_is_gone() -> None:
    """R3.1 (D35): the synthetic replay route and its switch are removed."""
    paths = {route.path for route in payment_hooks.router.routes}
    assert "/payment-complete" in paths
    assert not any(path.startswith("/payment-complete-test") for path in paths)


async def test_init_reconciler_alerts_overwatch(monkeypatch) -> None:
    messages = []

    class _WALogger:
        async def info(self, msg):
            messages.append(msg)

    async def _get_wa_logger():
        return _WALogger()

    monkeypatch.setattr(payment_hooks, "get_wa_logger", _get_wa_logger)
    bg = _FakeBackgroundTasks()
    request = payment_hooks.InitReconcilerRequest(
        orders=[{"order_id": "ABCD-1", "order_number": "ELAS-ABCD-1", "action": "delivery", "authorised_at": "2026-10-01T10:00:00Z"}]
    )

    assert await payment_hooks.init_reconciler_path(request, bg) == {"alerted": 1}
    task = bg.tasks[0]
    await task["func"](*task["args"])
    assert "ELAS-ABCD-1" in messages[0]
