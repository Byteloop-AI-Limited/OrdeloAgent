"""Tests for delivery webhook router functions.

Router callables are invoked directly with fake background tasks and patched
side-effect helpers, covering dispatch scheduling, inflight initialization,
missed dispatch updates, timeout notifications, availability fan-out, and
restaurant confirmation routing.

Key Functions:
  - test_wa_send_delivery_dispatch_request_to_rider_builds_accept_decline_buttons
  - test_delivery_dispatch_hook_empty_and_overwatch_scheduling
  - test_delivery_inflight_graph_init_hook_schedules_core_background_tasks
  - test_notify_missed_dispatches_hook_updates_dispatches_and_schedules_messages
  - test_notify_food_ready_for_pickup_schedules_rider_agent
  - test_delivery_timedout_notifies_admins_and_schedules_non_test_webhook
  - test_check_rider_allocation_status_returns_summary_status
  - test_shift_and_admin_availability_hooks_schedule_background_processing
  - test_restaurant_confirmation_flow_routes_and_validates_payload
  - test_handle_restaurant_timedout_uses_rest_specific_delivery_pickup_config
  - test_handle_restaurant_timedout_falls_back_to_global_delivery_pickup_config
  - test_handle_restaurant_timedout_falls_back_to_hardcoded_30_minutes_delivery
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

from watomation.routers import delivery_hooks
from tests.fixtures.fake_supabase import FakeSupabaseResponse
from tests.fixtures.fake_wa import FakeAsyncWhatsApp


class _FakeBackgroundTasks:
    def __init__(self) -> None:
        self.tasks = []

    def add_task(self, func, *args, **kwargs):
        self.tasks.append({"func": func, "args": args, "kwargs": kwargs})


def _summary_row(**overrides):
    row = {
        "order_number": "ELAS-ABCD-1",
        "rest_id": "REST001",
        "rest_name": "Elai",
        "rest_lon": -0.1278,
        "rest_lat": 51.5074,
        "rest_address": "1 Test Street",
        "town": "London",
        "customer_id": "447400000000",
        "customer_name": "Test Customer",
        "customer_lon": -0.1378,
        "customer_lat": 51.5174,
        "customer_address": "2 Customer Road",
        "status": "assigned",
        "restaurant_confirmation_status": "restaurant_unconfirmed",
        "rest_confirmation_code": 11,
        "cust_confirmation_code": 22,
        "pickup_time": datetime(2026, 5, 9, 12, 30, tzinfo=timezone.utc),
        "pickup_date": date(2026, 5, 9),
        "rest_ref": "ELAS",
        "dt": date(2026, 5, 9),
        "dtts": datetime(2026, 5, 9, 10, 0, tzinfo=timezone.utc),
        "distance": 2.3,
        "rider_payout": 5.5,
        "vehicle_type": "bike",
    }
    row.update(overrides)
    return row


def _restaurant_payload(trigger_reason="restaurant_unconfirmed", admins=None):
    admins = ["ADMIN01"] if admins is None else admins
    delivery_summary = {
        **_summary_row(),
        "pickup_time": None,
        "pickup_date": "2026-05-09",
        "dt": "2026-05-09",
        "dtts": "2026-05-09T10:00:00+00:00",
    }
    return {
        "trigger_reason": trigger_reason,
        "delivery_summary": delivery_summary,
        "restaurant_master": {
            "rest_id": "REST001",
            "rest_ref": "ELAS",
            "rest_name": "Elai",
            "admins": admins,
            "lon": -0.1278,
            "lat": 51.5074,
        },
        "food_order": {
            "order_id": "ABCD-1",
            "order_number": "ELAS-ABCD-1",
            "recipient": "447400000000",
            "thread_id": "thread-1",
            "action": "delivery",
            "total_price": 20.0,
            "payment_status": "requires_payment",
        },
        "order_items": [
            {"order_id": "ABCD-1", "sku": "burger", "quantity": 2, "price": 5.0, "product_name": "Burger"}
        ],
    }


async def test_wa_send_delivery_dispatch_request_to_rider_builds_accept_decline_buttons(fake_async_wa: FakeAsyncWhatsApp) -> None:
    await delivery_hooks.wa_send_delivery_dispatch_request_to_rider("RIDER01", _summary_row(), 10, _async_wa_client=fake_async_wa)

    sent = fake_async_wa.sent[-1]
    assert sent.kwargs["to"] == "RIDER01"
    assert "2.3 miles" in sent.kwargs["header"]
    payloads = [json.loads(button.callback_data) for button in sent.kwargs["buttons"]]
    assert {payload["status"] for payload in payloads} == {"accepted", "declined"}


async def test_delivery_dispatch_hook_empty_and_overwatch_scheduling(monkeypatch) -> None:
    import config.params as params

    bg = _FakeBackgroundTasks()
    assert await delivery_hooks.delivery_dispatch_hook(bg, payload={}) == {"status": "success"}

    monkeypatch.setattr(params, "get_overwatch_list", lambda: ["CUST01"])
    payload = {
        "bulk_dispatch": [
            {**_summary_row(customer_id="CUST01"), "rider_id": "OTHER", "dispatch_id": 1},
            {**_summary_row(customer_id="CUST01"), "rider_id": "CUST01", "dispatch_id": 2},
            {**_summary_row(customer_id="CUST02"), "rider_id": "RIDER02", "dispatch_id": 3},
        ]
    }

    result = await delivery_hooks.delivery_dispatch_hook(bg, payload=payload)

    assert result == {"status": "success"}
    assert [task["kwargs"]["recipient"] for task in bg.tasks] == ["CUST01", "RIDER02"]


async def test_delivery_inflight_graph_init_hook_schedules_core_background_tasks() -> None:
    bg = _FakeBackgroundTasks()
    payload = {
        "delivery_inflight": [{"dispatch_id": 10}],
        "delivery_summary": _summary_row(),
        "rider_master": {"rider_id": "RIDER01", "rider_name": "Bas"},
    }

    result = await delivery_hooks.delivery_inflight_graph_init_hook(bg, payload=payload)

    assert result == {"status": "success"}
    assert [task["func"] for task in bg.tasks] == [
        delivery_hooks.capture_payment,
        delivery_hooks.post_rider_event_inflight,
        delivery_hooks.admin_order_reciept,
        delivery_hooks.init_ordelo_graph,
        delivery_hooks.notify_overwatch,
    ]
    assert bg.tasks[3]["kwargs"]["rider_id"] == "RIDER01"


async def test_notify_missed_dispatches_hook_updates_dispatches_and_schedules_messages(monkeypatch, patch_supabase_client, patch_async_wa_client: FakeAsyncWhatsApp) -> None:
    monkeypatch.setattr(delivery_hooks, "client", patch_supabase_client)
    patch_supabase_client.register(table="delivery_dispatch", verb="update", response=FakeSupabaseResponse(data=[{"ok": True}]))
    bg = _FakeBackgroundTasks()

    result = await delivery_hooks.notify_missed_dispatches_hook(
        bg,
        payload={"missed_dispatches": [{"order_number": "ELAS-ABCD-1", "dispatches": [{"rider_id": "RIDER01", "dispatch_id": 10}]}]},
    )

    assert result == {"status": "success"}
    assert bg.tasks[0]["kwargs"]["to"] == "RIDER01"
    assert patch_supabase_client.calls[-1].filters["in:dispatch_id"] == [10]


async def test_notify_food_ready_for_pickup_schedules_rider_agent() -> None:
    bg = _FakeBackgroundTasks()

    result = await delivery_hooks.notify_food_ready_for_pickup("RIDER01", bg, payload={"restaurant_name": "Elai"})

    assert result["status"] == "success"
    assert bg.tasks[0]["func"] == delivery_hooks.run_rider_agent_w_custom_msg
    assert "Elai" in bg.tasks[0]["kwargs"]["system_msg"]


async def test_delivery_timedout_notifies_admins_and_schedules_non_test_webhook(monkeypatch, patch_async_wa_client: FakeAsyncWhatsApp) -> None:
    async def _fake_cancel(order_number):
        return "cancelled"

    monkeypatch.setattr(delivery_hooks, "cancel_payment", _fake_cancel)
    monkeypatch.setattr(delivery_hooks, "get_restaurant_admins", lambda rest_id=None, rest_ref=None: ["ADMIN01", "ADMIN02"])
    bg = _FakeBackgroundTasks()

    result = await delivery_hooks.delivery_timedout(bg, payload={"delivery_summary": [_summary_row(order_number="ELAS-ABCD-1")]})

    assert result == {"status": "success"}
    assert [sent.kwargs["to"] for sent in patch_async_wa_client.sent[-2:]] == ["ADMIN01", "ADMIN02"]
    assert bg.tasks[0]["func"] == delivery_hooks.post_delivery_timedout


async def test_check_rider_allocation_status_returns_summary_status(monkeypatch, patch_supabase_client) -> None:
    monkeypatch.setattr(delivery_hooks, "client", patch_supabase_client)
    patch_supabase_client.register(table="delivery_summary", verb="select", response=FakeSupabaseResponse(data=[{"status": "unassigned"}]))

    assert await delivery_hooks.check_rider_allocation_status("ELAS-ABCD-1") == {"delivery_summary_status": "unassigned"}


async def test_shift_and_admin_availability_hooks_schedule_background_processing(patch_supabase_client) -> None:
    bg = _FakeBackgroundTasks()
    result = await delivery_hooks.shift_availability_enquiry_hook(
        payload={"event_type": "shift", "riders": [{"rider_id": "RIDER01", "rider_name": "Bas"}]},
        background_tasks=bg,
    )
    assert result == {"status": "success", "riders_scheduled": 1}
    assert patch_supabase_client.calls[-1].payload["is_in_shift"] is False
    assert bg.tasks[-1]["func"] == delivery_hooks._process_shift_availability

    bg2 = _FakeBackgroundTasks()
    result = await delivery_hooks.admin_availability_enquiry_hook(
        payload={"event_type": "admin", "restaurant_admins": {"ELAS": ["ADMIN01", "ADMIN02"]}},
        background_tasks=bg2,
    )
    assert result == {"status": "success", "admins_scheduled": 2}
    assert bg2.tasks[-1]["func"] == delivery_hooks._process_admin_availability


async def test_restaurant_confirmation_flow_routes_and_validates_payload() -> None:
    bg = _FakeBackgroundTasks()
    result = await delivery_hooks.restaurant_confirmation_flow(bg, payload=_restaurant_payload("restaurant_accept"))
    assert result["status"] == "accepted"
    assert bg.tasks[0]["func"] == delivery_hooks._handle_restaurant_accept

    result = await delivery_hooks.restaurant_confirmation_flow(_FakeBackgroundTasks(), payload=_restaurant_payload("restaurant_unknown"))
    assert result["status"] == "error"
    assert "Unknown trigger_reason" in result["message"]

    result = await delivery_hooks.restaurant_confirmation_flow(_FakeBackgroundTasks(), payload=_restaurant_payload("restaurant_accept", admins=[]))
    assert result == {"status": "error", "message": "No restaurant contacts", "order_number": "ELAS-ABCD-1"}


async def test_handle_restaurant_timedout_uses_rest_specific_delivery_pickup_config(
    monkeypatch, patch_supabase_client, patch_async_wa_client: FakeAsyncWhatsApp
) -> None:
    monkeypatch.setattr(delivery_hooks, "client_ordelo", patch_supabase_client)
    patch_supabase_client.register(
        table="ordelo_config",
        verb="select",
        response=FakeSupabaseResponse(data=[{"config_value": "45"}]),
    )
    patch_supabase_client.register(
        table="delivery_summary",
        verb="update",
        response=FakeSupabaseResponse(data=[{"ok": True}]),
    )
    from watomation.routers.delivery_hooks import DeliverySummaryData
    summary = DeliverySummaryData(**{**_summary_row(), "pickup_time": None, "pickup_date": "2026-05-09", "dt": "2026-05-09", "dtts": "2026-05-09T10:00:00+00:00", "rest_ref": "SFCS"})

    result = await delivery_hooks._handle_restaurant_timedout(summary, ["ADMIN01"])

    assert result["status"] == "success"
    update_call = next(c for c in patch_supabase_client.calls if c.table == "delivery_summary")
    assert update_call.payload["pickup_time"] == "2026-05-09T11:45:00+01:00"
    assert "45 mins" in patch_async_wa_client.sent[-1].kwargs["text"]


async def test_handle_restaurant_timedout_falls_back_to_global_delivery_pickup_config(
    monkeypatch, patch_supabase_client, patch_async_wa_client: FakeAsyncWhatsApp
) -> None:
    monkeypatch.setattr(delivery_hooks, "client_ordelo", patch_supabase_client)

    def config_response(call):
        if call.filters.get("eq:config_key") == "ELAS_DELIVERY_PICKUP_DEFAULT_TIME":
            return FakeSupabaseResponse(data=[])
        return FakeSupabaseResponse(data=[{"config_value": "20"}])

    patch_supabase_client.register(table="ordelo_config", verb="select", response=config_response)
    patch_supabase_client.register(
        table="delivery_summary",
        verb="update",
        response=FakeSupabaseResponse(data=[{"ok": True}]),
    )
    from watomation.routers.delivery_hooks import DeliverySummaryData
    summary = DeliverySummaryData(**{**_summary_row(), "pickup_time": None, "pickup_date": "2026-05-09", "dt": "2026-05-09", "dtts": "2026-05-09T10:00:00+00:00"})

    await delivery_hooks._handle_restaurant_timedout(summary, ["ADMIN01"])

    update_call = next(c for c in patch_supabase_client.calls if c.table == "delivery_summary")
    assert update_call.payload["pickup_time"] == "2026-05-09T11:20:00+01:00"


async def test_handle_restaurant_timedout_falls_back_to_hardcoded_30_minutes_delivery(
    monkeypatch, patch_supabase_client, patch_async_wa_client: FakeAsyncWhatsApp
) -> None:
    monkeypatch.setattr(delivery_hooks, "client_ordelo", patch_supabase_client)
    patch_supabase_client.register(
        table="delivery_summary",
        verb="update",
        response=FakeSupabaseResponse(data=[{"ok": True}]),
    )
    from watomation.routers.delivery_hooks import DeliverySummaryData
    summary = DeliverySummaryData(**{**_summary_row(), "pickup_time": None, "pickup_date": "2026-05-09", "dt": "2026-05-09", "dtts": "2026-05-09T10:00:00+00:00"})

    await delivery_hooks._handle_restaurant_timedout(summary, ["ADMIN01"])

    update_call = next(c for c in patch_supabase_client.calls if c.table == "delivery_summary")
    assert update_call.payload["pickup_time"] == "2026-05-09T11:30:00+01:00"
