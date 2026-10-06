"""Tests for Ordelo agent app handler helpers.

Covers OwnTracks config generation, rider callback state transitions,
delivery-instruction message composition, live-location lookup, and webhook
posting without real WhatsApp, DB, or network calls.

Key Functions:
  - test_generate_config_href_round_trips_payload
  - test_create_start_and_stop_job_configs_encode_expected_fields
  - test_initial_handle_accept_decline_and_unavailable_branches
  - test_initial_handle_assigned_decline_triggers_cancel_flow
  - test_is_live_location_enabled_uses_rider_location_rows
  - test_send_delivery_instructions_composes_buttons_and_returns_message_id
  - test_post_rider_event_webhooks_call_configured_urls
"""

from __future__ import annotations

import base64
import json
from datetime import date, datetime, timezone

import httpx
import pytest
import respx

from ordelo import agent_app_handlers
from ordelo_datamodels.delivery_pymodels import DeliverySummary
from tests.fixtures.fake_supabase import FakeSupabaseResponse
from tests.fixtures.fake_wa import FakeAsyncWhatsApp


def _decode_config_href(href: str) -> dict:
    encoded = href.split("inline=", 1)[1]
    return json.loads(base64.b64decode(encoded).decode())


def _delivery_summary_row(**overrides):
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
        "rest_confirmation_code": 11,
        "cust_confirmation_code": 22,
        "pickup_time": datetime(2026, 5, 9, 12, 30, tzinfo=timezone.utc),
        "pickup_date": date(2026, 5, 9),
        "rest_ref": "ELAS",
        "dt": date(2026, 5, 9),
        "dtts": datetime(2026, 5, 9, 10, 0, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def test_generate_config_href_round_trips_payload() -> None:
    href = agent_app_handlers.generate_config_href({"mode": 3, "username": "rider"})

    assert href.startswith("owntracks:///config?inline=")
    assert _decode_config_href(href) == {"mode": 3, "username": "rider"}


async def test_create_start_and_stop_job_configs_encode_expected_fields() -> None:
    summary = DeliverySummary(**_delivery_summary_row())

    start = _decode_config_href(await agent_app_handlers.create_start_job_config(summary, "RIDER01"))
    stop = _decode_config_href(await agent_app_handlers.create_stop_job_config())

    assert start["username"] == "RIDER01"
    assert start["deviceId"] == "RIDER01-ELAS-ABCD-1"
    assert start["waypoints"][0]["lat"] == 51.5074
    assert start["waypoints"][1]["rid"] == "cust"
    assert stop["allowRemoteLocation"] is False
    assert stop["monitoring"] == -1


async def test_initial_handle_accept_decline_and_unavailable_branches(monkeypatch, patch_supabase_client, patch_async_wa_client: FakeAsyncWhatsApp) -> None:
    monkeypatch.setattr(agent_app_handlers, "client", patch_supabase_client)

    await agent_app_handlers.initial_handle_of_rider_response(
        {"status": "unassigned"},
        {"dispatch_id": 10, "order_number": "ELAS-ABCD-1", "rider_id": "RIDER01", "status": "accepted"},
    )
    assert patch_supabase_client.calls[-1].table == "delivery_dispatch"
    assert patch_supabase_client.calls[-1].verb == "update"
    assert patch_supabase_client.calls[-1].payload == {"status": "accepted"}

    patch_supabase_client.register(table="delivery_dispatch", verb="update", response=FakeSupabaseResponse(data=[]))
    await agent_app_handlers.initial_handle_of_rider_response(
        {"status": "unassigned"},
        {"dispatch_id": 11, "order_number": "ELAS-ABCD-1", "rider_id": "RIDER01", "status": "declined"},
    )
    assert patch_supabase_client.calls[-1].filters["in:status"] == ["unassigned", "accepted"]

    await agent_app_handlers.initial_handle_of_rider_response(
        {"status": "completed"},
        {"dispatch_id": 12, "order_number": "ELAS-ABCD-1", "rider_id": "RIDER01", "status": "accepted"},
        _async_wa_client=patch_async_wa_client,
    )
    assert patch_async_wa_client.sent[-1].kwargs["text"] == "Sorry, This job is no longer available"


async def test_initial_handle_assigned_decline_triggers_cancel_flow(monkeypatch, patch_supabase_client) -> None:
    from ordelo.agents import agent_runner

    monkeypatch.setattr(agent_app_handlers, "client", patch_supabase_client)
    patch_supabase_client.register(
        table="delivery_dispatch",
        verb="update",
        response=FakeSupabaseResponse(data=[{"dispatch_id": 10}]),
    )
    calls = []

    async def _fake_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(agent_runner, "run_rider_agent_w_custom_msg", _fake_run)

    await agent_app_handlers.initial_handle_of_rider_response(
        {"status": "assigned"},
        {"dispatch_id": 10, "order_number": "ELAS-ABCD-1", "rider_id": "RIDER01", "status": "declined"},
    )

    assert calls == [
        {
            "recipient": "RIDER01",
            "system_msg": "call `tool cancel_delivery_before_pickup`",
            "human_msg": "I need to cancel order ELAS-ABCD-1 before pickup.",
        }
    ]


def test_is_live_location_enabled_uses_rider_location_rows(patch_supabase_client) -> None:
    patch_supabase_client.register(table="rider_location", verb="select", response=FakeSupabaseResponse(data=[{"lat": 1}]))
    assert agent_app_handlers.is_live_location_enabled("ELAS-ABCD-1") is True
    assert patch_supabase_client.calls[-1].filters["like:order_number"] == "ELAS-ABCD-1"

    patch_supabase_client.register(table="rider_location", verb="select", response=FakeSupabaseResponse(data=[]))
    assert agent_app_handlers.is_live_location_enabled("ELAS-ABCD-1") is False


async def test_send_delivery_instructions_composes_buttons_and_returns_message_id(patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp) -> None:
    patch_supabase_client.register(
        table="delivery_dispatch",
        verb="select",
        response=FakeSupabaseResponse(data=[{"dispatch_id": 10, "order_number": "ELAS-ABCD-1", "rider_payout": 5.5, "distance": 2.3}]),
    )
    patch_supabase_client.register(
        table="delivery_summary",
        verb="select",
        response=FakeSupabaseResponse(data=[_delivery_summary_row()]),
    )

    msg_id, body = await agent_app_handlers._send_delivery_instructions(
        10,
        "RIDER01",
        "Bas",
        patch_supabase_client,
        fake_async_wa,
    )

    assert msg_id == "wamid.send_message.1"
    assert "Hi Bas" in body
    assert "£5.5" in body
    sent = fake_async_wa.sent[0]
    assert sent.kwargs["header"] == "🌟 ELAS-ABCD-1 🌟"
    assert [button.title for button in sent.kwargs["buttons"]] == ["Pickup Location", "Dropoff Location", "Contact Customer"]


@respx.mock
async def test_post_rider_event_webhooks_call_configured_urls(monkeypatch, inline_notifier) -> None:
    async def _fake_webhook(rest_ref: str, webhook_type: str) -> str:
        return f"https://restaurant.example.com/{rest_ref}/{webhook_type}"

    inline_notifier.webhook = _fake_webhook
    inline_notifier.recipient = "4474"
    cust_route = respx.post("https://restaurant.example.com/ELAS/rider-cust-cc/ELAS-ABCD-1/4474").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    rest_route = respx.post("https://restaurant.example.com/ELAS/rider-rest-cc/ELAS-ABCD-1/4474").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    await agent_app_handlers.post_rider_event_customer_cc("ELAS-ABCD-1", 4474)
    await agent_app_handlers.post_rider_event_restaurant_cc("ELAS-ABCD-1", 4474)

    assert cust_route.called
    assert rest_route.called
