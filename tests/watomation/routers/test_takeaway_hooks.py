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
  - test_handle_pickup_time_set_posts_webhook_and_sends_receipt
  - test_handle_pickup_time_updated_background_generates_print_url
  - test_init_takeaway_order_requires_customer_id
  - test_format_pickup_time_display_delegates_to_fmt_uk_time
  - test_pickup_time_updated_hook_schedules_background_processing
  - test_pickup_time_updated_hook_returns_error_for_invalid_payload
  - test_pickup_time_updated_hook_schedules_admin_receipt_for_configured_auto_accept
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from tests.fixtures.fake_supabase import FakeSupabaseResponse
from tests.fixtures.fake_wa import FakeAsyncWhatsApp
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

    assert result == {"status": "accepted", "message": "pickup_time_set handler scheduled", "order_number": "ELAS-ABCD-1"}
    assert bg.tasks[0]["func"] == takeaway_hooks._handle_pickup_time_updated_background
    assert bg.tasks[0]["args"][0].pickup_time == "2026-05-09T12:30:00+00:00"


async def test_pickup_time_updated_hook_returns_error_for_invalid_payload() -> None:
    result = await takeaway_hooks.pickup_time_updated_hook(
        SimpleNamespace(add_task=lambda *args, **kwargs: None),
        payload={"takeaway_summary": {"order_number": "ELAS-ABCD-1"}},
    )

    assert result["status"] == "error"
    assert result["order_number"] == "ELAS-ABCD-1"


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
        takeaway_hooks.takeaway_admin_order_receipt,
        takeaway_hooks.notify_overwatch,
    ]


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
