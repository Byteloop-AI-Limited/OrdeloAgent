"""Tests for payment webhook router helpers.

Payment hooks are invoked directly with fake request/background objects,
Supabase responses, and respx HTTP mocks to verify payment-complete fan-out,
summary initialization scheduling, and pay-at-restaurant validation.

Key Functions:
  - test_handle_payment_complete_posts_restaurant_webhook_and_swallows_http_errors
  - test_payment_complete_path_updates_order_and_schedules_delivery_or_takeaway
  - test_payment_complete_test_path_schedules_expected_initializer
  - test_pay_at_restaurant_validates_action_and_schedules_takeaway
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
async def test_handle_payment_complete_posts_restaurant_webhook_and_swallows_http_errors(monkeypatch) -> None:
    async def _webhook(rest_ref, webhook_type):
        return "https://rest.example.com/payment-complete"

    monkeypatch.setattr(payment_hooks, "get_restaurant_webhook_url_async", _webhook)
    route = respx.post("https://rest.example.com/payment-complete/447400000000/thread-1").mock(return_value=httpx.Response(200, json={"ok": True}))
    food_order = payment_hooks.FoodOrder(**_food_order_row())

    assert await payment_hooks.handle_payment_complete(food_order) == {"success": "success"}
    assert route.called

    respx.post("https://rest.example.com/payment-complete/447400000000/thread-1").mock(return_value=httpx.Response(500, json={"error": "down"}))
    assert await payment_hooks.handle_payment_complete(food_order) == {"success": "success"}


async def test_payment_complete_path_updates_order_and_schedules_delivery_or_takeaway(patch_supabase_client) -> None:
    patch_supabase_client.register(table="food_order", verb="update", response=FakeSupabaseResponse(data=[_food_order_row("delivery")]))
    bg = _FakeBackgroundTasks()
    payload = {"data": {"object": {"metadata": {"orderID": "ABCD-1"}}}}

    result = await payment_hooks.payment_complete_path(_FakeRequest(payload), bg)

    assert result == {"success": "success"}
    assert patch_supabase_client.calls[-1].payload == {"payment_status": "requires_capture"}
    assert [task["func"] for task in bg.tasks] == [payment_hooks.handle_payment_complete, payment_hooks.init_delivery_summary]

    patch_supabase_client.register(table="food_order", verb="update", response=FakeSupabaseResponse(data=[_food_order_row("takeaway")]))
    bg = _FakeBackgroundTasks()
    await payment_hooks.payment_complete_path(_FakeRequest(payload), bg)
    assert [task["func"] for task in bg.tasks] == [payment_hooks.handle_payment_complete, payment_hooks.init_takeaway_summary]


async def test_payment_complete_test_path_schedules_expected_initializer() -> None:
    delivery_bg = _FakeBackgroundTasks()
    assert await payment_hooks.payment_complete_test_path("ELAS-ABCD-1", delivery_bg, recipient="4474", action="delivery") == {"success": "success"}
    assert delivery_bg.tasks[0]["func"] == payment_hooks.init_delivery_summary

    takeaway_bg = _FakeBackgroundTasks()
    await payment_hooks.payment_complete_test_path("ELAS-ABCD-1", takeaway_bg, recipient="4474", action="takeaway")
    assert takeaway_bg.tasks[0]["func"] == payment_hooks.init_takeaway_summary


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
