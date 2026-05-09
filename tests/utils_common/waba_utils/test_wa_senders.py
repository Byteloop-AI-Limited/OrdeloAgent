"""Tests for representative WhatsApp sender helpers.

The fake WhatsApp client records outbound sends so tests assert template names,
headers, button callback data, and target recipients without contacting pywa.

Key Functions:
  - test_callback_button_data_is_frozen_and_allows_extra_fields
  - test_send_restaurant_pickup_time_creates_interval_buttons
  - test_confirm_delivery_address_wa_sends_yes_update_buttons
  - test_send_request_payment_link_uses_request_payment_template
  - test_send_order_reciept_wa_uses_receipt_template
  - test_enquire_shift_availability_template_has_yes_no_callbacks
  - test_enquire_admin_availability_template_has_admin_callback
  - test_send_restaurant_order_confirmation_creates_accept_button
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from utils_common.waba_utils import wa_senders
from tests.fixtures.fake_wa import FakeAsyncWhatsApp


def test_callback_button_data_is_frozen_and_allows_extra_fields() -> None:
    data = wa_senders.CallbackButtonData(action="/x", recipient="4474")
    assert data.action == "/x"
    assert data.model_dump()["recipient"] == "4474"

    with pytest.raises(ValidationError):
        data.action = "/y"


async def test_send_restaurant_pickup_time_creates_interval_buttons(patch_async_wa_client: FakeAsyncWhatsApp) -> None:
    epoch = int(datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc).timestamp())

    await wa_senders.send_restaurant_pickup_time(
        "447400000000",
        "Header",
        "Pick a time",
        "ELAS-ABCD-1",
        epoch,
        intervals_mins=[5, 15],
        order_type="takeaway",
    )

    sent = patch_async_wa_client.sent[-1]
    assert sent.method == "send_message"
    assert sent.kwargs["to"] == "447400000000"
    assert len(sent.kwargs["buttons"]) == 2
    callback = json.loads(sent.kwargs["buttons"][0].callback_data)
    assert callback["action"] == "/PickupTime"
    assert callback["order_type"] == "takeaway"


async def test_confirm_delivery_address_wa_sends_yes_update_buttons(patch_async_wa_client: FakeAsyncWhatsApp) -> None:
    await wa_senders.confirm_delivery_address_wa(
        "447400000000",
        {"house_number": "1", "street_name": "High St", "city": "London", "postcode": "SW1A"},
    )

    sent = patch_async_wa_client.sent[-1]
    assert sent.kwargs["header"] == "Confirm or Update Delivery Address"
    assert len(sent.kwargs["buttons"]) == 2
    yes_payload = json.loads(sent.kwargs["buttons"][0].callback_data)
    no_payload = json.loads(sent.kwargs["buttons"][1].callback_data)
    assert yes_payload["response"] == "Yes"
    assert no_payload["response"] == "No"


async def test_send_request_payment_link_uses_request_payment_template(fake_async_wa: FakeAsyncWhatsApp) -> None:
    await wa_senders.send_request_payment_link(
        "447400000000",
        "Bas",
        "https://pay.example.com/x",
        "ABCD-1",
        _async_wa_client=fake_async_wa,
    )

    sent = fake_async_wa.sent[-1]
    assert sent.method == "send_template"
    assert sent.kwargs["name"] == "request_payment"


async def test_send_order_reciept_wa_uses_receipt_template(fake_async_wa: FakeAsyncWhatsApp) -> None:
    await wa_senders.send_order_reciept_wa(
        "447400000000",
        ["a", "b", "c", "d"],
        _async_wa_client=fake_async_wa,
    )

    sent = fake_async_wa.sent[-1]
    assert sent.kwargs["name"] == "payment_reciept_elai"


async def test_enquire_shift_availability_template_has_yes_no_callbacks(patch_async_wa_client: FakeAsyncWhatsApp) -> None:
    await wa_senders.enquire_shift_availability(patch_async_wa_client, "447400000000", "Bas")

    sent = patch_async_wa_client.sent[-1]
    assert sent.method == "send_template"
    assert sent.kwargs["name"] == "shift_availability"
    callbacks = [param.callback_data for param in sent.kwargs["params"] if hasattr(param, "callback_data")]
    payloads = [json.loads(callback) for callback in callbacks]
    assert {payload["human_msg"] for payload in payloads} == {"Yes", "No"}


async def test_enquire_admin_availability_template_has_admin_callback(patch_async_wa_client: FakeAsyncWhatsApp) -> None:
    await wa_senders.enquire_admin_availability("447400000000")

    sent = patch_async_wa_client.sent[-1]
    assert sent.kwargs["name"] == "alert_order_notification_resolve"
    callbacks = [param.callback_data for param in sent.kwargs["params"] if hasattr(param, "callback_data")]
    assert json.loads(callbacks[0])["action"] == "/adminAvailability"


async def test_send_restaurant_order_confirmation_creates_accept_button(patch_async_wa_client: FakeAsyncWhatsApp) -> None:
    await wa_senders.send_restaurant_order_confirmation(
        "447400000000",
        "ELAS-ABCD-1",
        "£20.00",
        "1 x Burger",
        1_768_000_000,
        "delivery",
    )

    sent = patch_async_wa_client.sent[-1]
    assert "🚚" in sent.kwargs["header"]
    assert len(sent.kwargs["buttons"]) == 1
    payload = json.loads(sent.kwargs["buttons"][0].callback_data)
    assert payload["action"] == "/RestaurantOrder-Accept"
