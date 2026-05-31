"""Tests for WhatsApp callback button handlers.

Callback handlers are exercised with fake pywa messages and patched side-effect
functions to cover dispatch gating, shift/admin availability, restaurant order
confirmation, pickup-time updates, and ready notifications.

Key Functions:
  - test_dispatch_response_handles_missing_and_inflight_orders
  - test_dispatch_response_falls_through_to_initial_handler
  - test_rider_request_location_handles_completed_missing_and_active_dispatch
  - test_handle_shift_availability_yes_no_and_on_job_paths
  - test_handle_admin_availability_replies
  - test_update_restaurant_order_status_success_and_stale_tap
  - test_restaurant_order_accept_decline_schedules_update
  - test_handle_pickup_time_selection_success_and_already_updated
  - test_admin_collection_ready_runs_rider_graph
  - test_admin_takeaway_ready_validates_and_posts_webhook
  - test_admin_adjust_pickup_time_updates_summary
  - test_admin_adjust_pickup_time_missing_data
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import respx

from watomation import on_callback_wa_handler as handler
from tests.fixtures.fake_supabase import FakeSupabaseResponse
from tests.fixtures.fake_wa import FakeAsyncWhatsApp, FakeMessage


class _FakeCallback:
    def __init__(self, *, data: str, sender: str = "ADMIN01") -> None:
        self.data = data
        self.sender = sender
        self.replies = []

    async def reply(self, text: str):
        self.replies.append(text)


def _dispatch_payload(**overrides) -> str:
    payload = {"command": "/dispatchResponse", "order_number": "ELAS-ABCD-1", "dispatch_id": 10, "status": "accepted"}
    payload.update(overrides)
    return json.dumps(payload)


async def test_dispatch_response_handles_missing_and_inflight_orders(patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp) -> None:
    patch_supabase_client.register(table="delivery_summary", verb="select", response=FakeSupabaseResponse(data=[]))
    await handler.dispatch_response(fake_async_wa, FakeMessage(sender="RIDER01", data=_dispatch_payload()))
    assert fake_async_wa.sent[-1].kwargs["text"] == "Sorry, This job is no longer available"

    patch_supabase_client.register(table="delivery_summary", verb="select", response=FakeSupabaseResponse(data=[{"status": "assigned"}]))
    patch_supabase_client.register(table="delivery_inflight", verb="select", response=FakeSupabaseResponse(data=[{"rider_id": "RIDER01", "dispatch_id": 10, "order_number": "ELAS-ABCD-1"}]))
    await handler.dispatch_response(fake_async_wa, FakeMessage(sender="RIDER01", data=_dispatch_payload(status="accepted")))
    assert fake_async_wa.sent[-1].kwargs["text"] == "Sorry, You are already on a job ELAS-ABCD-1"

    patch_supabase_client.register(table="delivery_inflight", verb="select", response=FakeSupabaseResponse(data=[{"rider_id": "OTHER", "dispatch_id": 10, "order_number": "ELAS-ABCD-1"}]))
    await handler.dispatch_response(fake_async_wa, FakeMessage(sender="RIDER01", data=_dispatch_payload()))
    assert fake_async_wa.sent[-1].kwargs["text"] == "Sorry, this job was picked up by another rider."


async def test_dispatch_response_falls_through_to_initial_handler(monkeypatch, patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp) -> None:
    patch_supabase_client.register(table="delivery_summary", verb="select", response=FakeSupabaseResponse(data=[{"status": "unassigned"}]))
    patch_supabase_client.register(table="delivery_inflight", verb="select", response=FakeSupabaseResponse(data=[]))
    calls = []

    async def _fake_initial(order_status, callback_data):
        calls.append((order_status, callback_data))

    monkeypatch.setattr(handler, "initial_handle_of_rider_response", _fake_initial)

    await handler.dispatch_response(fake_async_wa, FakeMessage(sender="RIDER01", data=_dispatch_payload()))

    assert calls == [({"status": "unassigned"}, {"order_number": "ELAS-ABCD-1", "dispatch_id": 10, "status": "accepted", "rider_id": "RIDER01"})]


async def test_rider_request_location_handles_completed_missing_and_active_dispatch(monkeypatch, fake_async_wa: FakeAsyncWhatsApp) -> None:
    monkeypatch.setattr(handler.DeliveryDispatch, "from_dispatch_id", classmethod(lambda cls, dispatch_id: (_ for _ in ()).throw(ValueError("missing"))))
    await handler.rider_request_location(fake_async_wa, FakeMessage(data=json.dumps({"dispatch_id": 1, "recipient": "RIDER01", "human_msg": "pickup"})))
    assert fake_async_wa.sent == []

    monkeypatch.setattr(handler.DeliveryDispatch, "from_dispatch_id", classmethod(lambda cls, dispatch_id: SimpleNamespace(status="completed")))
    await handler.rider_request_location(fake_async_wa, FakeMessage(data=json.dumps({"dispatch_id": 1, "recipient": "RIDER01", "human_msg": "pickup"})))
    assert fake_async_wa.sent[-1].kwargs["text"] == "This job is expired."

    calls = []

    async def _fake_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(handler.DeliveryDispatch, "from_dispatch_id", classmethod(lambda cls, dispatch_id: SimpleNamespace(status="assigned")))
    monkeypatch.setattr(handler, "run_rider_agent_w_custom_msg", _fake_run)
    await handler.rider_request_location(fake_async_wa, FakeMessage(data=json.dumps({"dispatch_id": 1, "recipient": "RIDER01", "human_msg": "pickup"})))
    assert calls == [{"recipient": "RIDER01", "human_msg": "pickup"}]


async def test_handle_shift_availability_yes_no_and_on_job_paths(patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp) -> None:
    yes = json.dumps({"recipient": "RIDER01", "human_msg": "Yes"})
    await handler.handle_shift_availability(fake_async_wa, FakeMessage(data=yes))
    assert fake_async_wa.sent[-1].kwargs["text"] == "Great! You will receive notifications for new jobs."
    assert patch_supabase_client.calls[-1].payload["is_in_shift"] is True

    patch_supabase_client.register(table="delivery_inflight", verb="select", response=FakeSupabaseResponse(data=[{"order_number": "ELAS-ABCD-1"}]))
    no = json.dumps({"recipient": "RIDER01", "human_msg": "No"})
    await handler.handle_shift_availability(fake_async_wa, FakeMessage(data=no))
    assert "currently on a job" in fake_async_wa.sent[-1].kwargs["text"]

    patch_supabase_client.register(table="delivery_inflight", verb="select", response=FakeSupabaseResponse(data=[]))
    await handler.handle_shift_availability(fake_async_wa, FakeMessage(data=no))
    assert fake_async_wa.sent[-1].kwargs["text"] == "Ok. You will not receive job notifications for the next 24 hrs."
    assert patch_supabase_client.calls[-1].payload == {"is_in_shift": False}


async def test_handle_admin_availability_replies() -> None:
    msg = FakeMessage(data=json.dumps({"recipient": "ADMIN01"}))

    await handler.handle_admin_availability(FakeAsyncWhatsApp(), msg)

    assert msg.replies == [{"text": "Great! You will receive notification for new orders for the next 24 hrs!"}]


async def test_update_restaurant_order_status_success_and_stale_tap(patch_supabase_client) -> None:
    patch_supabase_client.register(table="delivery_summary", verb="update", response=FakeSupabaseResponse(data=[{"ok": True}]))
    msg = FakeMessage(sender="ADMIN01")

    await handler._update_restaurant_order_status("ELAS-ABCD-1", "restaurant_accept", msg)

    assert patch_supabase_client.calls[-1].payload["restaurant_confirmation_status"] == "restaurant_accept"
    assert msg.replies == []

    patch_supabase_client.register(table="delivery_summary", verb="update", response=FakeSupabaseResponse(data=[]))
    await handler._update_restaurant_order_status("ELAS-ABCD-1", "restaurant_accept", msg)
    assert msg.replies[-1] == {"text": "Order Already Accepted"}


async def test_restaurant_order_accept_decline_schedules_update(monkeypatch, fake_async_wa: FakeAsyncWhatsApp) -> None:
    scheduled = []

    def _fake_create_task(coro):
        scheduled.append(coro)
        coro.close()
        return SimpleNamespace(cancel=lambda: None)

    async def _fake_update(*args, **kwargs):
        return None

    monkeypatch.setattr(handler.asyncio, "create_task", _fake_create_task)
    monkeypatch.setattr(handler, "_update_restaurant_order_status", _fake_update)
    data = json.dumps({"action": "/RestaurantOrder-Accept", "order_number": "ELAS-ABCD-1", "order_time": 123, "order_type": "delivery"})

    await handler.restaurant_order_accept_decline_handler(fake_async_wa, FakeMessage(sender="ADMIN01", data=data))

    assert len(scheduled) == 1


async def test_handle_pickup_time_selection_success_and_already_updated(patch_supabase_client) -> None:
    data = json.dumps({"action": "/PickupTime", "order_number": "ELAS-ABCD-1", "pickup_time": 1_700_000_000, "order_type": "delivery"})
    msg = FakeMessage(sender="ADMIN01", data=data)
    patch_supabase_client.register(table="delivery_summary", verb="update", response=FakeSupabaseResponse(data=[{"ok": True}]))

    await handler.handle_pickup_time_selection(FakeAsyncWhatsApp(), msg)
    assert msg.replies[-1] == {"text": "Pickup time updated"}
    assert patch_supabase_client.calls[-1].filters["is:pickup_time"] == "null"

    patch_supabase_client.register(table="delivery_summary", verb="update", response=FakeSupabaseResponse(data=[]))
    await handler.handle_pickup_time_selection(FakeAsyncWhatsApp(), msg)
    assert msg.replies[-1] == {"text": "Pickup time already updated"}


async def test_admin_adjust_pickup_time_updates_summary(patch_supabase_client) -> None:
    patch_supabase_client.register(table="delivery_summary", verb="update", response=FakeSupabaseResponse(data=[{"ok": True}]))
    callback = _FakeCallback(
        data=json.dumps({
            "action": "/AdminAdjustPickupTime10",
            "order_number": "ELAS-ABCD-1",
            "pickup_time": "2026-05-09T11:40:00+00:00",
        }),
        sender="ADMIN01",
    )

    await handler.admin_adjust_pickup_time(FakeAsyncWhatsApp(), callback)

    update_call = patch_supabase_client.calls[-1]
    assert update_call.table == "delivery_summary"
    assert update_call.payload["pickup_time"] == "2026-05-09T11:40:00+00:00"
    assert update_call.payload["restaurant_confirmation_status"] == "restaurant_pickuptime_adjusted"
    assert update_call.payload["restaurant_admin"] == "ADMIN01"
    assert update_call.filters["eq:order_number"] == "ELAS-ABCD-1"
    assert callback.replies  # admin received a confirmation


async def test_admin_adjust_pickup_time_missing_data(patch_supabase_client) -> None:
    callback = _FakeCallback(data=json.dumps({"action": "/AdminAdjustPickupTime10"}))

    await handler.admin_adjust_pickup_time(FakeAsyncWhatsApp(), callback)

    assert callback.replies[-1] == "Missing order or pickup time in callback. Please retry."


async def test_admin_collection_ready_runs_rider_graph(monkeypatch) -> None:
    calls = []

    async def _fake_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(handler, "run_rider_agent_w_custom_msg", _fake_run)
    callback = _FakeCallback(data=json.dumps({"action": "/AdminCollectionReady", "rider_id": "RIDER01", "restaurant_name": "Elai"}))

    await handler.admin_collection_ready(FakeAsyncWhatsApp(), callback)

    assert calls[0]["recipient"] == "RIDER01"
    assert "notify_food_ready_for_pickup" in calls[0]["human_msg"]


@respx.mock
async def test_admin_takeaway_ready_validates_and_posts_webhook(monkeypatch) -> None:
    invalid = _FakeCallback(data=json.dumps({"action": "/AdminTakeawayReady", "order_number": "BAD"}))
    await handler.admin_takeaway_ready(FakeAsyncWhatsApp(), invalid)
    assert invalid.replies == ["Missing order number in callback. Please retry."]

    async def _webhook(rest_ref, webhook_type):
        return "https://rest.example.com/takeaway-ready"

    monkeypatch.setattr(handler, "get_restaurant_webhook_url_async", _webhook)
    route = respx.post("https://rest.example.com/takeaway-ready/ABCD-1").mock(return_value=httpx.Response(200, json={"ok": True}))
    callback = _FakeCallback(data=json.dumps({"action": "/AdminTakeawayReady", "order_number": "ELAS-ABCD-1", "recipient": "4474"}), sender="ADMIN01")

    await handler.admin_takeaway_ready(FakeAsyncWhatsApp(), callback)

    assert route.called
    assert callback.replies[-1] == "Customer notification request sent."
