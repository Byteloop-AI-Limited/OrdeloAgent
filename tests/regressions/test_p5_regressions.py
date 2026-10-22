"""Regression tests for issues fixed during the test-coverage rollout.

These tests lock in bug fixes from P2-P4 and add narrow negative-path checks at
external boundaries without contacting WhatsApp, Supabase, Stripe, or restaurant
webhooks.

Key Functions:
  - test_payment_and_reservation_templates_use_pywa_param_objects
  - test_cancel_delivery_before_pickup_reads_rider_name_from_state_not_context
  - test_dispatch_decline_for_same_inflight_dispatch_reaches_cancel_logic
  - test_admin_takeaway_ready_records_failed_restaurant_notice
  - test_location_customer_enter_records_webhook_http_error
  - test_restaurant_confirmation_flow_returns_error_for_invalid_payload
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
import respx

from ordelo.agents import rider_agent
from tests.fixtures.fake_supabase import FakeSupabaseResponse
from tests.fixtures.fake_wa import FakeAsyncWhatsApp, FakeMessage
from utils_common.waba_utils import wa_senders
from watomation import on_callback_wa_handler
from watomation.routers import delivery_hooks, location_hooks


def _runtime(*, client, wa, recipient="RIDER01"):
    return SimpleNamespace(context=SimpleNamespace(client_ordelo=client, wa_client=wa, recipient=recipient))


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
        "pickup_time": None,
        "pickup_date": "2026-05-09",
        "rest_ref": "ELAS",
        "dt": "2026-05-09",
        "dtts": "2026-05-09T10:00:00+00:00",
    }
    row.update(overrides)
    return row


class _FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


class _FakeCallback:
    def __init__(self, *, data: str, sender: str = "ADMIN01") -> None:
        self.data = data
        self.sender = sender
        self.replies = []

    async def reply(self, text: str):
        self.replies.append(text)


async def test_payment_and_reservation_templates_use_pywa_param_objects(fake_async_wa: FakeAsyncWhatsApp) -> None:
    await wa_senders.send_request_payment_link(
        "447400000000",
        "Bas",
        "https://pay.example.com/session",
        "ABCD-1",
        _async_wa_client=fake_async_wa,
    )
    payment = fake_async_wa.sent[-1]
    assert payment.kwargs["language"] == wa_senders.TemplateLanguage.ENGLISH_UK
    assert [param.named for param in payment.kwargs["params"][:2]] == [{"text": "Bas"}, {"text": "ABCD-1"}]
    assert payment.kwargs["params"][2].url_variable == "https://pay.example.com/session"
    assert payment.kwargs["params"][2].index == 0

    await wa_senders.send_reservation_link(
        "447400000000",
        "Bas",
        "RES123",
        _async_wa_client=fake_async_wa,
    )
    reservation = fake_async_wa.sent[-1]
    assert reservation.kwargs["name"] == "send_reservation_link"
    assert [param.named for param in reservation.kwargs["params"][:2]] == [{"text": "Bas"}, {"text": "RES123"}]
    assert reservation.kwargs["params"][2].url_variable == "RES123"

    await wa_senders.send_order_reciept_wa(
        "447400000000",
        ["order", "items", "total", "time"],
        _async_wa_client=fake_async_wa,
    )
    receipt = fake_async_wa.sent[-1]
    assert receipt.kwargs["name"] == "payment_reciept_elai"
    assert [param.named for param in receipt.kwargs["params"]] == [
        {"text": "order"},
        {"text": "items"},
        {"text": "total"},
        {"text": "time"},
    ]


async def test_cancel_delivery_before_pickup_reads_rider_name_from_state_not_context(patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp) -> None:
    patch_supabase_client.register_rpc("dispatch_cancel_before_pickup", FakeSupabaseResponse(data={"ok": True}))
    runtime = _runtime(client=patch_supabase_client, wa=fake_async_wa)
    assert not hasattr(runtime.context, "rider_name")

    result = await rider_agent.cancel_delivery_before_pickup(
        {"dispatch_id": 10, "order_number": "ELAS-ABCD-1", "rider_name": "Bas"},
        "tool-1",
        runtime,
    )

    assert "Ok Bas" in result.update["messages"][0].content
    assert result.update["awaiting_cancel_reason"] is True


async def test_dispatch_decline_for_same_inflight_dispatch_reaches_cancel_logic(monkeypatch, patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp) -> None:
    patch_supabase_client.register(table="delivery_summary", verb="select", response=FakeSupabaseResponse(data=[{"status": "inflight"}]))
    patch_supabase_client.register(table="delivery_inflight", verb="select", response=FakeSupabaseResponse(data=[{"rider_id": "RIDER01", "dispatch_id": 10, "order_number": "ELAS-ABCD-1"}]))
    # The assigned dispatch is found (the decline is for the rider's own live job) -> the cancel-before-pickup flow.
    patch_supabase_client.register(table="delivery_dispatch", verb="update", response=FakeSupabaseResponse(data=[{"dispatch_id": 10, "status": "assigned"}]))
    calls = []

    async def _fake_run(**kwargs):
        calls.append(kwargs)

    # Since R4 the offer rules live in ordelo.dispatch_actions.respond_to_offer (shared with Telegram, D48).
    monkeypatch.setattr("ordelo.agents.agent_runner.run_rider_agent_w_custom_msg", _fake_run)
    msg = FakeMessage(
        sender="RIDER01",
        data=json.dumps({"command": "/dispatchResponse", "order_number": "ELAS-ABCD-1", "dispatch_id": 10, "status": "declined"}),
    )

    await on_callback_wa_handler.dispatch_response(fake_async_wa, msg)

    assert fake_async_wa.sent == []  # no "already on a job" text for a decline of the same dispatch
    assert calls == [{
        "recipient": "RIDER01",
        "dispatch_id": 10,
        "system_msg": "call `tool cancel_delivery_before_pickup`",
        "human_msg": "I need to cancel order ELAS-ABCD-1 before pickup.",
    }]


@respx.mock
async def test_admin_takeaway_ready_records_failed_restaurant_notice(monkeypatch, inline_notifier, actions_db) -> None:
    """Since R3.1 the notifier records a failed restaurant-app notice (no retry); the admin's tap is acknowledged."""
    actions_db.add("ELAS-ABCD-1", "takeaway", rider=None, recipient="4474")   # Ready is now decided in SQL (restaurant_actions)
    async def _webhook(rest_ref, webhook_type):
        return "https://rest.example.com/takeaway-ready"

    inline_notifier.webhook = _webhook
    inline_notifier.recipient = "4474"
    respx.post("https://rest.example.com/takeaway-ready/ABCD-1").mock(return_value=httpx.Response(500, json={"error": "boom"}))
    callback = _FakeCallback(
        data=json.dumps({"action": "/AdminTakeawayReady", "order_number": "ELAS-ABCD-1", "recipient": "4474"}),
        sender="ADMIN01",
    )

    await on_callback_wa_handler.admin_takeaway_ready(FakeAsyncWhatsApp(), callback)

    assert callback.replies == ["Customer notification request sent."]
    assert [status for _, status, _ in inline_notifier.finished] == ["failed"]


@respx.mock
async def test_location_customer_enter_records_webhook_http_error(monkeypatch, patch_supabase_client, inline_notifier) -> None:
    patch_supabase_client.register(
        table="delivery_summary",
        verb="select",
        response=FakeSupabaseResponse(data=[{"order_number": "ELAS-ABCD-1", "rest_ref": "ELAS", "rest_confirmation_code": 11}]),
    )

    async def _webhook(rest_ref, webhook_type):
        return "https://rest.example.com/customer-enter"

    inline_notifier.webhook = _webhook
    inline_notifier.recipient = "4474"
    respx.post("https://rest.example.com/customer-enter/ELAS-ABCD-1").mock(return_value=httpx.Response(503, json={"error": "down"}))

    await location_hooks.notify_rider_location_event(
        _FakeRequest({"event": "enter", "rid": "cust", "customer_id": "4474", "order_number": "ELAS-ABCD-1"}),
        background_tasks=None,
    )

    assert respx.calls.call_count == 1
    assert [status for _, status, _ in inline_notifier.finished] == ["failed"]


async def test_restaurant_confirmation_flow_returns_error_for_invalid_payload() -> None:
    result = await delivery_hooks.restaurant_confirmation_flow(
        SimpleNamespace(add_task=lambda *args, **kwargs: None),
        payload={"trigger_reason": "restaurant_accept"},
    )

    assert result["status"] == "error"
    assert result["order_number"] == "unknown"
    assert "validation" in result["message"].lower() or "field required" in result["message"].lower()
