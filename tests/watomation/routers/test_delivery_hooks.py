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
  - test_notify_food_ready_for_pickup_skips_once_food_is_picked_up
  - test_notify_food_ready_for_pickup_skips_when_progress_unknown
  - test_delivery_timedout_notifies_admins_and_schedules_non_test_webhook
  - test_delivery_timedout_skips_no_rider_admin_message_for_configured_auto_accept
  - test_check_rider_allocation_status_returns_summary_status
  - test_shift_and_admin_availability_hooks_schedule_background_processing
  - test_restaurant_confirmation_flow_routes_and_validates_payload
  - test_restaurant_confirmation_flow_routes_pickuptime_adjusted
  - test_handle_restaurant_pickuptime_adjusted_notifies_inflight_rider
  - test_handle_restaurant_pickuptime_adjusted_skips_when_no_inflight
  - test_handle_restaurant_pickuptime_adjusted_skips_once_food_is_picked_up
  - test_handle_restaurant_pickuptime_adjusted_skips_when_progress_unknown
  - test_rider_pickup_alerts_hook_schedules_background_processing
  - test_rider_pickup_alerts_hook_ignores_empty_payload
  - test_process_rider_pickup_alerts_drives_agent_with_offset_cue
  - test_process_rider_pickup_alerts_skips_once_food_is_picked_up
  - test_process_rider_pickup_alerts_skips_when_progress_unknown
  - test_process_rider_pickup_alerts_isolates_a_failing_alert
  - test_process_rider_pickup_alerts_in_transit_runs_agent_when_picked_up
  - test_process_rider_pickup_alerts_in_transit_skipped_while_awaiting_pickup
  - test_process_rider_pickup_alerts_unknown_phase_is_skipped
  - test_process_rider_pickup_alerts_missing_phase_defaults_to_awaiting_pickup
  - test_process_rider_pickup_alerts_ops_audience_escalates_instead_of_running_agent
  - test_process_rider_pickup_alerts_ops_audience_skipped_on_phase_mismatch
  - test_process_rider_pickup_alerts_unknown_audience_is_skipped
  - test_process_rider_pickup_alerts_missing_audience_defaults_to_rider
  - test_process_rider_pickup_alerts_rest_admins_audience_messages_admins_not_agent_or_overwatch
  - test_process_rider_pickup_alerts_rest_admins_audience_skipped_on_phase_mismatch
  - test_process_rider_pickup_alerts_three_audiences_on_one_tick_are_all_delivered
  - test_process_rider_pickup_alerts_sends_to_the_rider_on_the_live_inflight_row
  - test_handle_restaurant_timedout_uses_rest_specific_delivery_pickup_config
  - test_handle_restaurant_timedout_falls_back_to_global_delivery_pickup_config
  - test_handle_restaurant_timedout_falls_back_to_hardcoded_30_minutes_delivery
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
import respx

from watomation.routers import delivery_hooks
from ordelo.delivery_progress import DeliveryProgress
from tests.fixtures.fake_supabase import FakeSupabaseResponse
from tests.fixtures.fake_wa import FakeAsyncWhatsApp


@pytest.fixture(autouse=True)
def cue_clears(monkeypatch):
    """Records clear_pickup_alert_cue calls and keeps them off the real DB pool.

    The router disarms the single-use pickup-alert cue after every rider run, which
    otherwise opens a live graph checkpointer and hangs the suite.
    """
    calls = []

    async def _clear(recipient):
        calls.append(recipient)

    monkeypatch.setattr(delivery_hooks, "clear_pickup_alert_cue", _clear)
    return calls


@pytest.fixture(autouse=True)
def normal_dispatch_audience(monkeypatch):
    async def allowed(*args):
        return True
    monkeypatch.setattr(delivery_hooks, "rider_dispatch_allowed", allowed)


class _FakeBackgroundTasks:
    def __init__(self) -> None:
        self.tasks = []

    def add_task(self, func, *args, **kwargs):
        self.tasks.append({"func": func, "args": args, "kwargs": kwargs})


def _progress(state: DeliveryProgress, row: dict | None = None):
    async def _check(**_kwargs):
        return state, row

    return _check


def _progress_by_order(state: DeliveryProgress, rows_by_order: dict):
    """Progress stub that resolves a different inflight row per order.

    The flat _progress() helper returns one fixed row for every call, which
    papers over a distinction the router now depends on: it takes the recipient
    from the live progress row rather than the payload, so an order re-dispatched
    between the sweep and the background task reaches the new rider.
    """

    async def _check(**kwargs):
        return state, rows_by_order.get(kwargs.get("order_number"))

    return _check


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
    bg = _FakeBackgroundTasks()
    assert await delivery_hooks.delivery_dispatch_hook(bg, payload={}) == {"status": "success"}
    classified = []
    reads = []
    async def marker(order_number):
        classified.append(order_number)
        return order_number == "ELAS-TEST-1"
    async def overwatch():
        reads.append(True)
        return frozenset({"OPS-RIDER"})
    monkeypatch.setattr(delivery_hooks, "order_has_test_item", marker)
    monkeypatch.setattr(delivery_hooks, "read_overwatch_riders", overwatch)
    payload = {"bulk_dispatch": [
        {**_summary_row(order_number="ELAS-TEST-1", customer_id="W-ANON"), "rider_id": "OTHER", "dispatch_id": 1},
        {**_summary_row(order_number="ELAS-TEST-1", customer_id="W-ANON"), "rider_id": "OPS-RIDER", "dispatch_id": 2},
        {**_summary_row(order_number="ELAS-LIVE-1", customer_id="OPS-RIDER"), "rider_id": "RIDER02", "dispatch_id": 3},
    ]}
    assert await delivery_hooks.delivery_dispatch_hook(bg, payload=payload) == {"status": "success"}
    assert [t["kwargs"]["recipient"] for t in bg.tasks] == ["OPS-RIDER", "RIDER02"]
    assert classified == ["ELAS-TEST-1", "ELAS-LIVE-1"]
    assert len(reads) == 1


async def test_dispatch_unknown_order_does_not_send_or_block_other_orders(monkeypatch):
    async def marker(number):
        if number == "UNKNOWN":
            raise RuntimeError("lookup failed")
        return False
    monkeypatch.setattr(delivery_hooks, "order_has_test_item", marker)
    bg = _FakeBackgroundTasks()
    await delivery_hooks.delivery_dispatch_hook(bg, payload={"bulk_dispatch": [
        {**_summary_row(order_number=n), "rider_id": "RIDER", "dispatch_id": i}
        for i,n in enumerate(["UNKNOWN", "ELAS-LIVE-1"])
    ]})
    assert len(bg.tasks) == 1
    assert bg.tasks[0]["kwargs"]["delivery_summary"]["order_number"] == "ELAS-LIVE-1"


async def test_blocked_stale_dispatch_and_missed_notice_never_send(monkeypatch, fake_async_wa):
    async def blocked(*args):
        return False
    monkeypatch.setattr(delivery_hooks, "rider_dispatch_allowed", blocked)
    monkeypatch.setattr(delivery_hooks, "_async_wa_client", fake_async_wa)
    await delivery_hooks.wa_send_delivery_dispatch_request_to_rider("OTHER", _summary_row(), 10, _async_wa_client=fake_async_wa)
    await delivery_hooks._send_missed_dispatch_if_allowed("ELAS-ABCD-1", "OTHER", "missed")
    assert fake_async_wa.sent == []


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
        delivery_hooks.capture_delivery_payment,
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


async def test_notify_food_ready_for_pickup_schedules_rider_agent(monkeypatch) -> None:
    bg = _FakeBackgroundTasks()
    monkeypatch.setattr(delivery_hooks, "check_delivery_progress", _progress(DeliveryProgress.AWAITING_PICKUP))

    result = await delivery_hooks.notify_food_ready_for_pickup("RIDER01", bg, payload={"restaurant_name": "Elai"})

    assert result["status"] == "success"
    assert bg.tasks[0]["func"] == delivery_hooks.run_rider_agent_w_custom_msg
    assert "Elai" in bg.tasks[0]["kwargs"]["system_msg"]


async def test_notify_food_ready_for_pickup_skips_once_food_is_picked_up(monkeypatch) -> None:
    bg = _FakeBackgroundTasks()
    monkeypatch.setattr(delivery_hooks, "check_delivery_progress", _progress(DeliveryProgress.PICKED_UP))

    result = await delivery_hooks.notify_food_ready_for_pickup("RIDER01", bg, payload={"restaurant_name": "Elai"})

    assert result["status"] == "skipped"
    assert result["action"] == "picked_up"
    assert bg.tasks == []


async def test_notify_food_ready_for_pickup_skips_when_progress_unknown(monkeypatch) -> None:
    # The only caller (restaurant-agent runtime, in the sibling repo) never
    # inspects the response, so a read failure returns "skipped" like every
    # other non-awaiting-pickup outcome rather than raising -- see the
    # docstring on notify_food_ready_for_pickup.
    bg = _FakeBackgroundTasks()
    monkeypatch.setattr(delivery_hooks, "check_delivery_progress", _progress(DeliveryProgress.UNKNOWN))

    result = await delivery_hooks.notify_food_ready_for_pickup("RIDER01", bg, payload={"restaurant_name": "Elai"})

    assert result["status"] == "skipped"
    assert result["action"] == "unknown"
    assert bg.tasks == []


async def test_delivery_timedout_notifies_admins_and_schedules_non_test_webhook(monkeypatch, patch_async_wa_client: FakeAsyncWhatsApp) -> None:
    async def _fake_cancel(order_number):
        return "cancelled"

    monkeypatch.setattr(delivery_hooks, "cancel_payment", _fake_cancel)
    monkeypatch.setattr(delivery_hooks.RestaurantMaster, "get_admins_for", classmethod(lambda cls, rest_ref: ["ADMIN01", "ADMIN02"]))
    bg = _FakeBackgroundTasks()

    result = await delivery_hooks.delivery_timedout(bg, payload={"delivery_summary": [_summary_row(order_number="ELAS-ABCD-1")]})

    assert result == {"status": "success"}
    assert [sent.kwargs["to"] for sent in patch_async_wa_client.sent[-2:]] == ["ADMIN01", "ADMIN02"]
    assert bg.tasks[0]["func"] == delivery_hooks.post_delivery_timedout
    assert bg.tasks[0]["kwargs"]["payment_cancelled"] is True


async def test_delivery_timedout_forwards_unconfirmed_cancellation(monkeypatch, patch_async_wa_client: FakeAsyncWhatsApp) -> None:
    async def _fake_cancel(order_number):
        return None

    monkeypatch.setattr(delivery_hooks, "cancel_payment", _fake_cancel)
    monkeypatch.setattr(delivery_hooks.RestaurantMaster, "get_admins_for", classmethod(lambda cls, rest_ref: []))
    bg = _FakeBackgroundTasks()

    await delivery_hooks.delivery_timedout(
        bg, payload={"delivery_summary": [_summary_row(order_number="ELAS-ABCD-1")]}
    )

    assert bg.tasks[0]["kwargs"]["payment_cancelled"] is False


async def test_delivery_timedout_skips_no_rider_admin_message_for_configured_auto_accept(
    monkeypatch, patch_async_wa_client: FakeAsyncWhatsApp
) -> None:
    async def _fake_cancel(order_number):
        return "cancelled"

    monkeypatch.setattr(delivery_hooks, "cancel_payment", _fake_cancel)
    monkeypatch.setattr(
        delivery_hooks.RestaurantMaster,
        "get_admins_for",
        classmethod(lambda cls, rest_ref: (_ for _ in ()).throw(AssertionError("must not load admins"))),
    )
    bg = _FakeBackgroundTasks()

    result = await delivery_hooks.delivery_timedout(
        bg,
        payload={
            "delivery_summary": [
                _summary_row(rest_confirmation_method="configured_auto")
            ]
        },
    )

    assert result == {"status": "success"}
    assert patch_async_wa_client.sent == []
    assert bg.tasks[0]["func"] == delivery_hooks.post_delivery_timedout


@respx.mock
async def test_timeout_webhook_serialises_verified_payment_cancellation(monkeypatch, inline_notifier) -> None:
    async def _webhook_url(rest_ref, webhook_type):
        assert (rest_ref, webhook_type) == ("ELAS", "delivery-timedout")
        return "https://rest.example.com/delivery-timedout"

    inline_notifier.webhook = _webhook_url
    route = respx.post("https://rest.example.com/delivery-timedout").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    await delivery_hooks.post_delivery_timedout(
        {"order_number": "ELAS-ABCD-1"}, payment_cancelled=True
    )

    assert route.called
    assert json.loads(route.calls.last.request.content)["payment_cancelled"] is True


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
        payload={
            "event_type": "admin",
            "restaurant_admins": {
                "ELAS": ["ADMIN01", "ADMIN02"],
                "BNAT": ["ADMIN02", "ADMIN03"],
            },
        },
        background_tasks=bg2,
    )
    assert result == {"status": "success", "admins_scheduled": 3}
    assert bg2.tasks[-1]["func"] == delivery_hooks._process_admin_availability
    assert bg2.tasks[-1]["args"][0] == {
        "ADMIN01": ["ELAS"],
        "ADMIN02": ["ELAS", "BNAT"],
        "ADMIN03": ["BNAT"],
    }


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


async def test_restaurant_confirmation_flow_routes_pickuptime_adjusted() -> None:
    bg = _FakeBackgroundTasks()
    result = await delivery_hooks.restaurant_confirmation_flow(
        bg, payload=_restaurant_payload("restaurant_pickuptime_adjusted")
    )
    assert result["status"] == "accepted"
    assert bg.tasks[0]["func"] == delivery_hooks._handle_restaurant_pickuptime_adjusted


def _adjusted_summary():
    from watomation.routers.delivery_hooks import DeliverySummaryData

    return DeliverySummaryData(**{
        **_summary_row(),
        "pickup_time": "2026-05-09T11:40:00+00:00",
        "pickup_date": "2026-05-09",
        "dt": "2026-05-09",
        "dtts": "2026-05-09T10:00:00+00:00",
    })


async def test_handle_restaurant_pickuptime_adjusted_notifies_inflight_rider(monkeypatch) -> None:
    monkeypatch.setattr(
        delivery_hooks,
        "check_delivery_progress",
        _progress(DeliveryProgress.AWAITING_PICKUP, {"rider_id": "RIDER01"}),
    )
    calls = []

    async def _fake_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(delivery_hooks, "run_rider_agent_w_custom_msg", _fake_run)

    result = await delivery_hooks._handle_restaurant_pickuptime_adjusted(_adjusted_summary())

    assert result["status"] == "success"
    assert calls[0]["recipient"] == "RIDER01"
    assert calls[0]["state_update_dict"]["pickup_time"] == "2026-05-09T11:40:00+00:00"
    assert "notify_pickup_time_adjusted" in calls[0]["system_msg"]


async def test_handle_restaurant_pickuptime_adjusted_skips_when_no_inflight(monkeypatch) -> None:
    monkeypatch.setattr(
        delivery_hooks, "check_delivery_progress", _progress(DeliveryProgress.NOT_IN_PROGRESS)
    )
    calls = []

    async def _fake_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(delivery_hooks, "run_rider_agent_w_custom_msg", _fake_run)

    result = await delivery_hooks._handle_restaurant_pickuptime_adjusted(_adjusted_summary())

    assert result["status"] == "skipped"
    assert result["action"] == "no_inflight_rider"
    assert calls == []


async def test_handle_restaurant_pickuptime_adjusted_skips_once_food_is_picked_up(monkeypatch) -> None:
    monkeypatch.setattr(
        delivery_hooks,
        "check_delivery_progress",
        _progress(DeliveryProgress.PICKED_UP, {"rider_id": "RIDER01"}),
    )
    calls = []

    async def _fake_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(delivery_hooks, "run_rider_agent_w_custom_msg", _fake_run)

    result = await delivery_hooks._handle_restaurant_pickuptime_adjusted(_adjusted_summary())

    assert result["status"] == "skipped"
    assert result["action"] == "already_picked_up"
    assert result["rider_id"] == "RIDER01"
    assert calls == []


async def test_handle_restaurant_pickuptime_adjusted_skips_when_progress_unknown(monkeypatch) -> None:
    monkeypatch.setattr(
        delivery_hooks, "check_delivery_progress", _progress(DeliveryProgress.UNKNOWN)
    )
    calls = []

    async def _fake_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(delivery_hooks, "run_rider_agent_w_custom_msg", _fake_run)

    result = await delivery_hooks._handle_restaurant_pickuptime_adjusted(_adjusted_summary())

    assert result["status"] == "skipped"
    assert result["action"] == "progress_unknown"
    assert calls == []


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


def _alert(**overrides):
    alert = {
        "order_number": "ELAS-ABCD-1",
        "rider_id": "RIDER01",
        "dispatch_id": 11,
        "phase": "awaiting_pickup",
        "audience": "rider",
        "offset_minutes": -5,
        "pickup_time": "2026-05-09T11:40:00+00:00",
        "minutes_since_pickup": -4.2,
        "rider_name": "Bas",
        "rest_name": "Elai",
        "rest_ref": "ELAS",
        "rest_admins": ["ADMIN01"],
    }
    alert.update(overrides)
    return alert


async def test_rider_pickup_alerts_hook_schedules_background_processing() -> None:
    bg = _FakeBackgroundTasks()
    alerts = [_alert(), _alert(order_number="ELAS-ABCD-2", rider_id="RIDER02")]

    result = await delivery_hooks.rider_pickup_alerts_hook(
        payload={"event_type": "rider_pickup_alerts", "alerts": alerts},
        background_tasks=bg,
    )

    assert result == {"status": "success", "alerts_scheduled": 2}
    assert bg.tasks[0]["func"] == delivery_hooks._process_rider_pickup_alerts
    assert bg.tasks[0]["args"][0] == alerts


async def test_rider_pickup_alerts_hook_ignores_empty_payload() -> None:
    bg = _FakeBackgroundTasks()

    result = await delivery_hooks.rider_pickup_alerts_hook(payload={}, background_tasks=bg)

    assert result == {"status": "success", "alerts_scheduled": 0}
    assert bg.tasks == []


async def test_process_rider_pickup_alerts_drives_agent_with_offset_cue(monkeypatch, cue_clears) -> None:
    monkeypatch.setattr(
        delivery_hooks,
        "check_delivery_progress",
        _progress(DeliveryProgress.AWAITING_PICKUP, {"rider_id": "RIDER01"}),
    )
    calls = []

    async def _fake_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(delivery_hooks, "run_rider_agent_w_custom_msg", _fake_run)

    await delivery_hooks._process_rider_pickup_alerts([_alert(offset_minutes=5)])

    assert len(calls) == 1
    assert calls[0]["recipient"] == "RIDER01"
    assert calls[0]["state_update_dict"] == {
        "pickup_alert_offset": 5,
        "pickup_alert_phase": "awaiting_pickup",
        # Sourced from the payload, not from whatever the thread last stored.
        "order_number": "ELAS-ABCD-1",
        "pickup_time": "2026-05-09T11:40:00+00:00",
    }
    assert cue_clears == ["RIDER01"]
    assert "notify_pickup_reminder" in calls[0]["system_msg"]


async def test_process_rider_pickup_alerts_skips_once_food_is_picked_up(monkeypatch) -> None:
    monkeypatch.setattr(
        delivery_hooks,
        "check_delivery_progress",
        _progress(DeliveryProgress.PICKED_UP, {"rider_id": "RIDER01"}),
    )
    calls = []

    async def _fake_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(delivery_hooks, "run_rider_agent_w_custom_msg", _fake_run)

    await delivery_hooks._process_rider_pickup_alerts([_alert()])

    assert calls == []


async def test_process_rider_pickup_alerts_skips_when_progress_unknown(monkeypatch) -> None:
    monkeypatch.setattr(
        delivery_hooks, "check_delivery_progress", _progress(DeliveryProgress.UNKNOWN)
    )
    calls = []

    async def _fake_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(delivery_hooks, "run_rider_agent_w_custom_msg", _fake_run)

    await delivery_hooks._process_rider_pickup_alerts([_alert()])

    assert calls == []


async def test_process_rider_pickup_alerts_isolates_a_failing_alert(monkeypatch) -> None:
    """One rider's alert blowing up must not cost the other riders theirs."""
    monkeypatch.setattr(
        delivery_hooks,
        "check_delivery_progress",
        _progress_by_order(
            DeliveryProgress.AWAITING_PICKUP,
            {
                "ELAS-ABCD-1": {"rider_id": "RIDER01"},
                "ELAS-ABCD-2": {"rider_id": "RIDER02"},
            },
        ),
    )
    calls = []

    async def _fake_run(**kwargs):
        if kwargs["recipient"] == "RIDER01":
            raise RuntimeError("graph unavailable")
        calls.append(kwargs)

    monkeypatch.setattr(delivery_hooks, "run_rider_agent_w_custom_msg", _fake_run)

    await delivery_hooks._process_rider_pickup_alerts(
        [_alert(), _alert(order_number="ELAS-ABCD-2", rider_id="RIDER02")]
    )

    assert [c["recipient"] for c in calls] == ["RIDER02"]


async def test_process_rider_pickup_alerts_in_transit_runs_agent_when_picked_up(monkeypatch) -> None:
    monkeypatch.setattr(
        delivery_hooks,
        "check_delivery_progress",
        _progress(DeliveryProgress.PICKED_UP, {"rider_id": "RIDER01"}),
    )
    calls = []

    async def _fake_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(delivery_hooks, "run_rider_agent_w_custom_msg", _fake_run)

    await delivery_hooks._process_rider_pickup_alerts(
        [_alert(phase="picked_up", offset_minutes=30)]
    )

    assert len(calls) == 1
    assert calls[0]["state_update_dict"] == {
        "pickup_alert_offset": 30,
        "pickup_alert_phase": "picked_up",
        # Sourced from the payload, not from whatever the thread last stored.
        "order_number": "ELAS-ABCD-1",
        "pickup_time": "2026-05-09T11:40:00+00:00",
    }


async def test_process_rider_pickup_alerts_in_transit_skipped_while_awaiting_pickup(monkeypatch) -> None:
    """The inverse of the awaiting-pickup case: a delivery-phase alert must not
    reach a rider who has not collected yet."""
    monkeypatch.setattr(
        delivery_hooks,
        "check_delivery_progress",
        _progress(DeliveryProgress.AWAITING_PICKUP, {"rider_id": "RIDER01"}),
    )
    calls = []

    async def _fake_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(delivery_hooks, "run_rider_agent_w_custom_msg", _fake_run)

    await delivery_hooks._process_rider_pickup_alerts(
        [_alert(phase="picked_up", offset_minutes=30)]
    )

    assert calls == []


async def test_process_rider_pickup_alerts_unknown_phase_is_skipped(monkeypatch) -> None:
    """An unrecognised phase must not silently fall back to a real one."""
    monkeypatch.setattr(
        delivery_hooks,
        "check_delivery_progress",
        _progress(DeliveryProgress.AWAITING_PICKUP, {"rider_id": "RIDER01"}),
    )
    calls = []

    async def _fake_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(delivery_hooks, "run_rider_agent_w_custom_msg", _fake_run)

    await delivery_hooks._process_rider_pickup_alerts([_alert(phase="in_the_air")])

    assert calls == []


async def test_process_rider_pickup_alerts_missing_phase_defaults_to_awaiting_pickup(monkeypatch) -> None:
    """Keeps a pre-phase payload working if the app is deployed ahead of the migration."""
    monkeypatch.setattr(
        delivery_hooks,
        "check_delivery_progress",
        _progress(DeliveryProgress.AWAITING_PICKUP, {"rider_id": "RIDER01"}),
    )
    calls = []

    async def _fake_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(delivery_hooks, "run_rider_agent_w_custom_msg", _fake_run)

    alert = _alert()
    del alert["phase"]
    await delivery_hooks._process_rider_pickup_alerts([alert])

    assert len(calls) == 1
    assert calls[0]["state_update_dict"]["pickup_alert_phase"] == "awaiting_pickup"


def _capture_escalations(monkeypatch) -> list:
    calls = []

    async def _fake_escalate(**kwargs):
        calls.append(kwargs)
        return {"overwatch": "sent"}

    monkeypatch.setattr(delivery_hooks, "notify_ops_rider_alert", _fake_escalate)
    return calls


def _capture_rest_admin_alerts(monkeypatch) -> list:
    calls = []

    async def _fake_notify(**kwargs):
        calls.append(kwargs)
        return {"admins_notified": 1, "admins_failed": 0}

    monkeypatch.setattr(delivery_hooks, "notify_rest_admins_rider_alert", _fake_notify)
    return calls


async def test_process_rider_pickup_alerts_ops_audience_escalates_instead_of_running_agent(monkeypatch) -> None:
    monkeypatch.setattr(
        delivery_hooks,
        "check_delivery_progress",
        _progress(DeliveryProgress.PICKED_UP, {"rider_id": "RIDER01"}),
    )
    escalations = _capture_escalations(monkeypatch)
    agent_calls = []

    async def _fake_run(**kwargs):
        agent_calls.append(kwargs)

    monkeypatch.setattr(delivery_hooks, "run_rider_agent_w_custom_msg", _fake_run)

    await delivery_hooks._process_rider_pickup_alerts(
        [_alert(audience="ops", phase="picked_up", offset_minutes=30)]
    )

    assert agent_calls == [], "ops escalations must never run the rider graph"
    assert len(escalations) == 1
    assert escalations[0]["phase"] == "picked_up"
    assert escalations[0]["order_number"] == "ELAS-ABCD-1"


async def test_process_rider_pickup_alerts_ops_audience_skipped_on_phase_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(
        delivery_hooks,
        "check_delivery_progress",
        _progress(DeliveryProgress.PICKED_UP, {"rider_id": "RIDER01"}),
    )
    escalations = _capture_escalations(monkeypatch)

    # An awaiting-pickup escalation must not fire once the food is collected.
    await delivery_hooks._process_rider_pickup_alerts(
        [_alert(audience="ops", phase="awaiting_pickup", offset_minutes=10)]
    )

    assert escalations == []


async def test_process_rider_pickup_alerts_unknown_audience_is_skipped(monkeypatch) -> None:
    monkeypatch.setattr(
        delivery_hooks,
        "check_delivery_progress",
        _progress(DeliveryProgress.AWAITING_PICKUP, {"rider_id": "RIDER01"}),
    )
    escalations = _capture_escalations(monkeypatch)
    agent_calls = []

    async def _fake_run(**kwargs):
        agent_calls.append(kwargs)

    monkeypatch.setattr(delivery_hooks, "run_rider_agent_w_custom_msg", _fake_run)

    await delivery_hooks._process_rider_pickup_alerts([_alert(audience="carrier_pigeon")])

    assert escalations == []
    assert agent_calls == []


async def test_process_rider_pickup_alerts_missing_audience_defaults_to_rider(monkeypatch) -> None:
    """Keeps a pre-audience payload working if the app is deployed ahead of the migration."""
    monkeypatch.setattr(
        delivery_hooks,
        "check_delivery_progress",
        _progress(DeliveryProgress.AWAITING_PICKUP, {"rider_id": "RIDER01"}),
    )
    escalations = _capture_escalations(monkeypatch)
    agent_calls = []

    async def _fake_run(**kwargs):
        agent_calls.append(kwargs)

    monkeypatch.setattr(delivery_hooks, "run_rider_agent_w_custom_msg", _fake_run)

    alert = _alert()
    del alert["audience"]
    await delivery_hooks._process_rider_pickup_alerts([alert])

    assert escalations == []
    assert len(agent_calls) == 1


async def test_process_rider_pickup_alerts_rest_admins_audience_messages_admins_not_agent_or_overwatch(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        delivery_hooks,
        "check_delivery_progress",
        _progress_by_order(
            DeliveryProgress.AWAITING_PICKUP, {"ELAS-ABCD-1": {"rider_id": "RIDER_NEW"}}
        ),
    )
    escalations = _capture_escalations(monkeypatch)
    rest_admin_alerts = _capture_rest_admin_alerts(monkeypatch)
    agent_calls = []

    async def _fake_run(**kwargs):
        agent_calls.append(kwargs)

    monkeypatch.setattr(delivery_hooks, "run_rider_agent_w_custom_msg", _fake_run)

    await delivery_hooks._process_rider_pickup_alerts(
        [_alert(audience="rest_admins", rider_id="RIDER_OLD", offset_minutes=7)]
    )

    assert escalations == []
    assert agent_calls == []
    assert len(rest_admin_alerts) == 1
    assert rest_admin_alerts[0]["order_number"] == "ELAS-ABCD-1"
    assert rest_admin_alerts[0]["rest_admins"] == ["ADMIN01"]
    # Live inflight row, not the payload's stale rider -- same guarantee as #4.
    assert rest_admin_alerts[0]["rider_id"] == "RIDER_NEW"


async def test_process_rider_pickup_alerts_rest_admins_audience_skipped_on_phase_mismatch(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        delivery_hooks,
        "check_delivery_progress",
        _progress(DeliveryProgress.PICKED_UP, {"rider_id": "RIDER01"}),
    )
    rest_admin_alerts = _capture_rest_admin_alerts(monkeypatch)

    # A still-awaiting-pickup rest_admins alert must not fire once collected.
    await delivery_hooks._process_rider_pickup_alerts(
        [_alert(audience="rest_admins", phase="awaiting_pickup", offset_minutes=7)]
    )

    assert rest_admin_alerts == []


async def test_process_rider_pickup_alerts_three_audiences_on_one_tick_are_all_delivered(
    monkeypatch,
) -> None:
    """Mirrors runbook step 6: rider/7, ops/10, rest_admins/7 due together for the
    same order. All three must be delivered from a single run."""
    monkeypatch.setattr(
        delivery_hooks,
        "check_delivery_progress",
        _progress(DeliveryProgress.AWAITING_PICKUP, {"rider_id": "RIDER01"}),
    )
    escalations = _capture_escalations(monkeypatch)
    rest_admin_alerts = _capture_rest_admin_alerts(monkeypatch)
    agent_calls = []

    async def _fake_run(**kwargs):
        agent_calls.append(kwargs)

    monkeypatch.setattr(delivery_hooks, "run_rider_agent_w_custom_msg", _fake_run)

    await delivery_hooks._process_rider_pickup_alerts(
        [
            _alert(audience="rider", offset_minutes=7),
            _alert(audience="ops", offset_minutes=10),
            _alert(audience="rest_admins", offset_minutes=7),
        ]
    )

    assert len(agent_calls) == 1
    assert len(escalations) == 1
    assert len(rest_admin_alerts) == 1


async def test_process_rider_pickup_alerts_sends_to_the_rider_on_the_live_inflight_row(
    monkeypatch, cue_clears
) -> None:
    """The payload's rider can be stale by the time the background task runs.

    If the original rider declines pre-pickup between the sweep's POST and this
    task, dispatch_cancel_before_pickup deletes the dispatch and the order is
    re-dispatched. The gate then reports AWAITING_PICKUP for the *new* rider, and
    sending to the payload's rider would nag someone about a job they no longer
    have.
    """
    monkeypatch.setattr(
        delivery_hooks,
        "check_delivery_progress",
        _progress_by_order(
            DeliveryProgress.AWAITING_PICKUP, {"ELAS-ABCD-1": {"rider_id": "RIDER_NEW"}}
        ),
    )
    calls = []

    async def _fake_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(delivery_hooks, "run_rider_agent_w_custom_msg", _fake_run)

    await delivery_hooks._process_rider_pickup_alerts([_alert(rider_id="RIDER_OLD")])

    assert [c["recipient"] for c in calls] == ["RIDER_NEW"]
    assert cue_clears == ["RIDER_NEW"]
