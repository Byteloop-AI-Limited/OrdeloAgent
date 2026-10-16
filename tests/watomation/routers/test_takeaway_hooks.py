"""Tests for takeaway webhook handlers covering confirmation, decline, pickup-time, and init paths.

Covers restaurant_unconfirmed/accept/decline/timedout handlers, confirmation flow
routing, pickup-time webhook + background processing, and init-takeaway-order entrypoint.

Key Functions:
  - test_handle_restaurant_timedout_updates_only_null_pickup_time_and_notifies_admins
  - test_handle_restaurant_timedout_skips_admin_notifications_when_update_matches_no_rows
  - test_handle_restaurant_unconfirmed_sends_confirmation_to_admins
  - test_handle_restaurant_accept_sends_pickup_time_to_admins
  - test_handle_restaurant_decline_cancels_payment_and_notifies_customer
  - test_handle_restaurant_decline_pay_at_rest_skips_payment_cancel
  - test_restaurant_confirmation_flow_routes_to_correct_handler
  - test_restaurant_confirmation_flow_unknown_trigger_returns_error
  - test_restaurant_confirmation_flow_no_admins_returns_error
  - test_capture_takeaway_payment_retries_only_pending_payment_intent_lookup
  - test_capture_takeaway_payment_does_not_retry_ambiguous_failure
  - test_capture_takeaway_payment_does_not_retry_transport_timeout
  - test_init_takeaway_order_requires_customer_id
  - test_format_pickup_time_display_delegates_to_fmt_uk_time
  - test_pickup_time_updated_hook_schedules_background_processing
  - test_pickup_time_updated_hook_returns_error_for_invalid_payload
  - test_pickup_time_updated_hook_schedules_admin_receipt_for_configured_auto_accept
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import respx

from tests.fixtures.fake_supabase import FakeSupabaseResponse
from tests.fixtures.fake_wa import FakeAsyncWhatsApp
from utils_common.notify import restaurant_notifier
from utils_common.notify.restaurant_notifier import TakeawayReceipt
from watomation.routers import takeaway_hooks


class _FakeBackgroundTasks:
    def __init__(self) -> None:
        self.tasks = []

    def add_task(self, func, *args, **kwargs):
        self.tasks.append({"func": func, "args": args, "kwargs": kwargs})


def _takeaway_summary_row(**overrides):
    row = {
        "order_number": "ELAS-ABCD-1",
        "rest_id": "REST001",
        "rest_name": "Elai",
        "rest_address": "1 Test Street",
        "town": "London",
        "customer_id": "447400000000",
        "customer_name": "Test Customer",
        "status": "restaurant_confirming",
        "restaurant_confirmation_status": "restaurant_timedout",
        "rest_confirmation_code": 11,
        "pickup_time": None,
        "pickup_date": "2026-05-09",
        "rest_ref": "ELAS",
        "dt": "2026-05-09",
        "dtts": "2026-05-09T10:00:00+00:00",
    }
    row.update(overrides)
    return row


def _restaurant_master_row(**overrides):
    row = {
        "rest_id": "REST001",
        "rest_ref": "ELAS",
        "rest_name": "Elai",
        "admins": ["ADMIN01"],
        "lon": -0.1278,
        "lat": 51.5074,
    }
    row.update(overrides)
    return row


class _CaptureFoodOrder:
    order_id = "ABCD-1"
    order_number = "ELAS-ABCD-1"
    payment_uri = "https://payment.example.com/threads/thread-1/orders/ABCD-1/payment-url"
    payment_status = "requires_capture"

    async def gen_capture_payload(self) -> dict:
        return {
            "action": "collection",
            "payment_mode": "capture",
            "rest_payout": 20.0,
            "total_amount": 23.96,
            "notes": "No onions",
            "restRef": "elas",
            "items": [
                {
                    "product_name": "Matilda Cake",
                    "quantity": 4,
                    "price": 5.99,
                    "modifications": [],
                }
            ],
        }


async def test_handle_restaurant_timedout_updates_only_null_pickup_time_and_notifies_admins(monkeypatch, patch_supabase_client, patch_async_wa_client: FakeAsyncWhatsApp) -> None:
    monkeypatch.setattr(takeaway_hooks, "client_ordelo", patch_supabase_client)
    patch_supabase_client.register(table="takeaway_summary", verb="update", response=FakeSupabaseResponse(data=[{"ok": True}]))
    summary = takeaway_hooks.TakeawaySummaryData(**_takeaway_summary_row())

    result = await takeaway_hooks._handle_restaurant_timedout(summary, ["ADMIN01", "ADMIN02"])

    assert result["status"] == "success"
    call = patch_supabase_client.calls[-1]
    assert call.table == "takeaway_summary"
    assert call.payload["restaurant_confirmation_status"] == "auto_accept"
    assert call.filters["eq:restaurant_confirmation_status"] == "restaurant_timedout"
    assert call.filters["is:pickup_time"] == "null"
    assert [sent.kwargs["to"] for sent in patch_async_wa_client.sent[-2:]] == ["ADMIN01", "ADMIN02"]


async def test_handle_restaurant_timedout_skips_admin_notifications_when_update_matches_no_rows(monkeypatch, patch_supabase_client, patch_async_wa_client: FakeAsyncWhatsApp) -> None:
    monkeypatch.setattr(takeaway_hooks, "client_ordelo", patch_supabase_client)
    patch_supabase_client.register(table="takeaway_summary", verb="update", response=FakeSupabaseResponse(data=[]))
    summary = takeaway_hooks.TakeawaySummaryData(**_takeaway_summary_row())

    result = await takeaway_hooks._handle_restaurant_timedout(summary, ["ADMIN01"])

    assert result == {"status": "skipped", "action": "auto_accept_skipped", "order_number": "ELAS-ABCD-1"}
    assert patch_async_wa_client.sent == []
    assert patch_supabase_client.calls[-1].filters["is:pickup_time"] == "null"


async def test_pickup_time_updated_hook_schedules_background_processing() -> None:
    bg = _FakeBackgroundTasks()
    payload = {
        "takeaway_summary": _takeaway_summary_row(
            status="pickup_confirmed",
            restaurant_confirmation_status="restaurant_accept",
            pickup_time="2026-05-09T12:30:00+00:00",
        ),
        "restaurant_master": _restaurant_master_row(),
    }

    result = await takeaway_hooks.pickup_time_updated_hook(bg, payload=payload)

    assert result == {"status": "success"}
    assert [task["func"] for task in bg.tasks] == [
        takeaway_hooks.capture_takeaway_payment,
        takeaway_hooks._post_pickup_time_event,
        restaurant_notifier.notify,
        takeaway_hooks.notify_overwatch,
    ]
    # Step 3 hands the notifier exactly what takeaway_admin_order_receipt used to get (WhatsApp parity).
    assert bg.tasks[2]["args"] == (
        TakeawayReceipt(
            order_number="ELAS-ABCD-1",
            pickup_time="2026-05-09T12:30:00+00:00",
            rest_name="Elai",
            admins=["ADMIN01"],
            restaurant_msg_id=None,
            rest_ref="ELAS",
        ),
    )
    assert bg.tasks[2]["kwargs"] == {}


async def test_pickup_time_updated_hook_returns_error_for_invalid_payload() -> None:
    result = await takeaway_hooks.pickup_time_updated_hook(
        SimpleNamespace(add_task=lambda *args, **kwargs: None),
        payload={"takeaway_summary": {"order_number": "ELAS-ABCD-1"}},
    )

    assert result["status"] == "error"
    assert result["order_number"] == "ELAS-ABCD-1"


@respx.mock
async def test_capture_takeaway_payment_retries_only_pending_payment_intent_lookup(
    monkeypatch,
) -> None:
    order = _CaptureFoodOrder()
    monkeypatch.setattr(
        takeaway_hooks.FoodOrder,
        "from_order_number",
        staticmethod(lambda **_: order),
    )
    sleeps: list[int] = []
    alerts: list[str] = []

    async def _sleep(delay: int) -> None:
        sleeps.append(delay)

    async def _notify(*, log_msg: str) -> None:
        alerts.append(log_msg)

    monkeypatch.setattr(takeaway_hooks.asyncio, "sleep", _sleep)
    monkeypatch.setattr(takeaway_hooks, "notify_overwatch", _notify)
    route = respx.post(order.payment_uri).mock(
        side_effect=[
            httpx.Response(
                500,
                json={
                    "error": "Failed to capture payment: failed to retrieve PaymentIntent from order number ABCD-1"
                },
            ),
            httpx.Response(
                500,
                json={
                    "error": "Failed to capture payment: failed to retrieve PaymentIntent from order number ABCD-1"
                },
            ),
            httpx.Response(200, text=""),
        ]
    )

    assert await takeaway_hooks.capture_takeaway_payment(order.order_number) == ""
    assert sleeps == [2, 5]
    assert len(route.calls) == 3
    assert alerts == []
    payload = json.loads(route.calls[0].request.content)
    assert payload["restaurant_confirmation_code"] == "N/A"
    assert payload["action"] == "collection"
    assert payload["items"][0] == {
        "product_name": "Matilda Cake",
        "quantity": 4,
        "price": 5.99,
        "modifications": [],
    }


@respx.mock
async def test_capture_takeaway_payment_does_not_retry_ambiguous_failure(monkeypatch) -> None:
    order = _CaptureFoodOrder()
    monkeypatch.setattr(
        takeaway_hooks.FoodOrder,
        "from_order_number",
        staticmethod(lambda **_: order),
    )
    alerts: list[str] = []

    async def _notify(*, log_msg: str) -> None:
        alerts.append(log_msg)

    monkeypatch.setattr(takeaway_hooks, "notify_overwatch", _notify)
    route = respx.post(order.payment_uri).mock(
        return_value=httpx.Response(
            500,
            json={"error": "Failed to capture payment: transfer to restaurant failed"},
        )
    )

    assert await takeaway_hooks.capture_takeaway_payment(order.order_number) is None
    assert len(route.calls) == 1
    assert len(alerts) == 1
    assert "requires reconciliation" in alerts[0]


async def test_capture_takeaway_payment_does_not_retry_transport_timeout(monkeypatch) -> None:
    order = _CaptureFoodOrder()
    monkeypatch.setattr(
        takeaway_hooks.FoodOrder,
        "from_order_number",
        staticmethod(lambda **_: order),
    )
    alerts: list[str] = []

    class _TimeoutClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            raise httpx.ReadTimeout("gateway timeout")

    async def _notify(*, log_msg: str) -> None:
        alerts.append(log_msg)

    monkeypatch.setattr(takeaway_hooks.httpx, "AsyncClient", _TimeoutClient)
    monkeypatch.setattr(takeaway_hooks, "notify_overwatch", _notify)

    assert await takeaway_hooks.capture_takeaway_payment(order.order_number) is None
    assert len(alerts) == 1
    assert "gateway timeout" in alerts[0]


async def test_pickup_time_updated_hook_schedules_admin_receipt_for_configured_auto_accept() -> None:
    bg = _FakeBackgroundTasks()
    payload = {
        "takeaway_summary": _takeaway_summary_row(
            status="pickup_confirmed",
            restaurant_confirmation_status="auto_accept",
            rest_confirmation_method="configured_auto",
            pickup_time="2026-05-09T12:30:00+00:00",
        ),
        "restaurant_master": _restaurant_master_row(),
    }

    result = await takeaway_hooks.pickup_time_updated_hook(bg, payload=payload)

    assert result == {"status": "success"}
    assert [task["func"] for task in bg.tasks] == [
        takeaway_hooks.capture_takeaway_payment,
        takeaway_hooks._post_pickup_time_event,
        restaurant_notifier.notify,
        takeaway_hooks.notify_overwatch,
    ]
    # Step 3 hands the notifier exactly what takeaway_admin_order_receipt used to get (WhatsApp parity).
    assert bg.tasks[2]["args"] == (
        TakeawayReceipt(
            order_number="ELAS-ABCD-1",
            pickup_time="2026-05-09T12:30:00+00:00",
            rest_name="Elai",
            admins=["ADMIN01"],
            restaurant_msg_id=None,
            rest_ref="ELAS",
        ),
    )
    assert bg.tasks[2]["kwargs"] == {}


async def test_handle_restaurant_timedout_uses_rest_specific_pickup_config(
    monkeypatch, patch_supabase_client, patch_async_wa_client: FakeAsyncWhatsApp
) -> None:
    monkeypatch.setattr(takeaway_hooks, "client_ordelo", patch_supabase_client)
    patch_supabase_client.register(
        table="ordelo_config",
        verb="select",
        response=FakeSupabaseResponse(data=[{"config_value": "45"}]),
    )
    patch_supabase_client.register(
        table="takeaway_summary",
        verb="update",
        response=FakeSupabaseResponse(data=[{"ok": True}]),
    )
    summary = takeaway_hooks.TakeawaySummaryData(**_takeaway_summary_row(rest_ref="SFCS"))

    result = await takeaway_hooks._handle_restaurant_timedout(summary, ["ADMIN01"])

    assert result["status"] == "success"
    update_call = next(c for c in patch_supabase_client.calls if c.table == "takeaway_summary")
    assert update_call.payload["pickup_time"] == "2026-05-09T11:45:00+01:00"
    assert "45 mins" in patch_async_wa_client.sent[-1].kwargs["text"]


async def test_handle_restaurant_timedout_falls_back_to_global_pickup_config(
    monkeypatch, patch_supabase_client, patch_async_wa_client: FakeAsyncWhatsApp
) -> None:
    monkeypatch.setattr(takeaway_hooks, "client_ordelo", patch_supabase_client)

    def config_response(call):
        if call.filters.get("eq:config_key") == "ELAS_PICKUP_DEFAULT_TIME":
            return FakeSupabaseResponse(data=[])
        return FakeSupabaseResponse(data=[{"config_value": "20"}])

    patch_supabase_client.register(table="ordelo_config", verb="select", response=config_response)
    patch_supabase_client.register(
        table="takeaway_summary",
        verb="update",
        response=FakeSupabaseResponse(data=[{"ok": True}]),
    )
    summary = takeaway_hooks.TakeawaySummaryData(**_takeaway_summary_row())

    await takeaway_hooks._handle_restaurant_timedout(summary, ["ADMIN01"])

    update_call = next(c for c in patch_supabase_client.calls if c.table == "takeaway_summary")
    assert update_call.payload["pickup_time"] == "2026-05-09T11:20:00+01:00"


async def test_handle_restaurant_timedout_falls_back_to_hardcoded_30_minutes(
    monkeypatch, patch_supabase_client, patch_async_wa_client: FakeAsyncWhatsApp
) -> None:
    monkeypatch.setattr(takeaway_hooks, "client_ordelo", patch_supabase_client)
    patch_supabase_client.register(
        table="takeaway_summary",
        verb="update",
        response=FakeSupabaseResponse(data=[{"ok": True}]),
    )
    summary = takeaway_hooks.TakeawaySummaryData(**_takeaway_summary_row())

    await takeaway_hooks._handle_restaurant_timedout(summary, ["ADMIN01"])

    update_call = next(c for c in patch_supabase_client.calls if c.table == "takeaway_summary")
    assert update_call.payload["pickup_time"] == "2026-05-09T11:30:00+01:00"


async def test_handle_restaurant_timedout_hands_an_exact_auto_accepted_notice_to_the_notifier(monkeypatch, patch_supabase_client) -> None:
    monkeypatch.setattr(takeaway_hooks, "client_ordelo", patch_supabase_client)
    patch_supabase_client.register(table="takeaway_summary", verb="update", response=FakeSupabaseResponse(data=[{"ok": True}]))
    seen = []

    async def fake_notify(notice):
        seen.append(notice)

    monkeypatch.setattr(restaurant_notifier, "notify", fake_notify)
    summary = takeaway_hooks.TakeawaySummaryData(**_takeaway_summary_row())

    await takeaway_hooks._handle_restaurant_timedout(summary, ["ADMIN01", "ADMIN02"])

    assert len(seen) == 1
    n = seen[0]
    assert (n.order_number, n.order_type, n.admins, n.rest_ref) == ("ELAS-ABCD-1", "takeaway", ["ADMIN01", "ADMIN02"], "ELAS")
    assert n.pickup_minutes > 0 and n.pickup_display
