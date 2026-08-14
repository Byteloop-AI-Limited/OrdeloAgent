"""Tests for location webhook router helpers.

Location hooks are invoked directly with fake requests, fake Supabase rows,
respx HTTP mocks, and fake WhatsApp clients to cover redirect decisions,
transition persistence, location event notifications, and live-tracking prompts.

Key Functions:
  - test_generate_config_href_round_trips_payload
  - test_process_location_transition_writes_expected_sql
  - test_process_location_transition_rejects_unknown_transition
  - test_live_location_map_validates_and_returns_url
  - test_notify_rider_location_event_restaurant_enter_notifies_admins
  - test_notify_rider_location_event_customer_enter_posts_webhook
  - test_notify_rider_null_or_outdated_location_sends_reason_messages
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx
from fastapi import HTTPException

from watomation.routers import location_hooks
from tests.fixtures.fake_supabase import FakeSupabaseResponse
from tests.fixtures.fake_wa import FakeAsyncWhatsApp


class _FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


def _decode_href(href: str) -> dict:
    return json.loads(base64.b64decode(href.split("inline=", 1)[1]).decode())


def _summary_row(**overrides):
    row = {
        "order_number": "ELAS-ABCD-1",
        "rest_ref": "ELAS",
        "rest_confirmation_code": 11,
        "customer_id": "447400000000",
    }
    row.update(overrides)
    return row


def test_generate_config_href_round_trips_payload() -> None:
    href = location_hooks.generate_config_href({"mode": 3})

    assert href.startswith("owntracks:///config?inline=")
    assert _decode_href(href) == {"mode": 3}


async def test_process_location_transition_writes_expected_sql(patch_pg_pool) -> None:
    payload = {
        "tst": 1_700_000_000,
        "topic": "owntracks/RIDER01/4474-ELAS-ABCD-1/event",
        "event": "enter",
        "rid": "rest",
    }

    assert await location_hooks.process_location_transitionTBD(payload) is True
    executed = patch_pg_pool.all_executes[-1]
    assert "INSERT INTO rider_location_event" in executed.sql
    assert executed.params[0] == payload["topic"]
    assert executed.params[1] == "RIDER01"
    assert executed.params[2] == "ELAS-ABCD-1"


async def test_process_location_transition_rejects_unknown_transition(patch_pg_pool) -> None:
    with pytest.raises(ValueError, match="No valid update statement"):
        await location_hooks.process_location_transitionTBD(
            {"tst": 1_700_000_000, "topic": "owntracks/RIDER01/4474-ELAS-ABCD-1/event", "event": "enter", "rid": "unknown"}
        )


async def test_live_location_map_validates_and_returns_url(monkeypatch) -> None:
    with pytest.raises(HTTPException) as bad:
        await location_hooks.live_location_map("none")
    assert bad.value.status_code == 400

    async def _missing(order_number):
        return None

    monkeypatch.setattr(location_hooks, "get_live_map_location_url", _missing)
    with pytest.raises(HTTPException) as missing:
        await location_hooks.live_location_map("ELAS-ABCD-1")
    assert missing.value.status_code == 404

    async def _found(order_number):
        return "https://maps.example.com"

    monkeypatch.setattr(location_hooks, "get_live_map_location_url", _found)
    assert await location_hooks.live_location_map("ELAS-ABCD-1") == "https://maps.example.com"


async def test_notify_rider_location_event_restaurant_enter_notifies_admins(monkeypatch, patch_supabase_client, patch_async_wa_client: FakeAsyncWhatsApp) -> None:
    patch_supabase_client.register(table="delivery_summary", verb="select", response=FakeSupabaseResponse(data=[_summary_row()]))
    monkeypatch.setattr(location_hooks.RestaurantMaster, "get_admins_for", classmethod(lambda cls, rest_ref: ["ADMIN01", "ADMIN02"]))

    await location_hooks.notify_rider_location_event(
        _FakeRequest({"event": "enter", "rid": "rest", "customer_id": "4474", "order_number": "ELAS-ABCD-1"}),
        background_tasks=None,
    )

    assert [sent.kwargs["to"] for sent in patch_async_wa_client.sent[-2:]] == ["ADMIN01", "ADMIN02"]
    assert "2 Digit Code" in patch_async_wa_client.sent[-1].kwargs["text"]


@respx.mock
async def test_notify_rider_location_event_customer_enter_posts_webhook(monkeypatch, patch_supabase_client) -> None:
    patch_supabase_client.register(table="delivery_summary", verb="select", response=FakeSupabaseResponse(data=[_summary_row()]))

    async def _webhook(rest_ref, webhook_type):
        return "https://rest.example.com/customer-enter"

    monkeypatch.setattr(location_hooks, "get_restaurant_webhook_url_async", _webhook)
    route = respx.post("https://rest.example.com/customer-enter/ELAS-ABCD-1").mock(return_value=httpx.Response(200, json={"ok": True}))

    await location_hooks.notify_rider_location_event(
        _FakeRequest({"event": "enter", "rid": "cust", "customer_id": "4474", "order_number": "ELAS-ABCD-1"}),
        background_tasks=None,
    )

    assert route.called


async def test_notify_rider_null_or_outdated_location_sends_reason_messages(
    monkeypatch, patch_async_wa_client: FakeAsyncWhatsApp
) -> None:
    monkeypatch.setattr(
        location_hooks.wa_location_settings,
        "legacy_owntracks_prompts_enabled",
        True,
    )
    await location_hooks.notify_rider_null_or_outdated_location(
        _FakeRequest(
            [
                {"rider_id": "RIDER01", "order_number": "ELAS-ABCD-1", "reason": "NO_LOCATION_DATA"},
                {"rider_id": "RIDER02", "order_number": "ELAS-ABCD-2", "reason": "OUTDATED_LOCATION_DATA"},
            ]
        )
    )

    assert patch_async_wa_client.sent[-2].kwargs["text"] == "Please enable live tracking to receive updates on your delivery."
    assert patch_async_wa_client.sent[-1].kwargs["text"] == "How is the delivery going? you seemed to have stopped."


async def test_notify_rider_null_or_outdated_location_is_disabled_by_default(
    monkeypatch, patch_async_wa_client: FakeAsyncWhatsApp
) -> None:
    monkeypatch.setattr(
        location_hooks.wa_location_settings,
        "legacy_owntracks_prompts_enabled",
        False,
    )

    response = await location_hooks.notify_rider_null_or_outdated_location(
        _FakeRequest([
            {"rider_id": "RIDER01", "order_number": "ELAS-ABCD-1", "reason": "NO_LOCATION_DATA"},
        ])
    )

    assert response == {"status": "disabled"}
    assert patch_async_wa_client.sent == []
