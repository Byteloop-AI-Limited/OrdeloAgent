"""Tests for representative WhatsApp sender helpers.

The fake WhatsApp client records outbound sends so tests assert template names,
headers, button callback data, and target recipients without contacting pywa.

Key Functions:
  - test_callback_button_data_is_frozen_and_allows_extra_fields
  - test_food_ready_y_callback_carries_order_number_within_button_payload_limit
  - test_send_restaurant_pickup_time_creates_interval_buttons
  - test_confirm_delivery_address_wa_sends_yes_update_buttons
  - test_send_request_payment_link_uses_request_payment_template
  - test_send_order_reciept_wa_uses_receipt_template
  - test_enquire_shift_availability_template_has_yes_no_callbacks
  - test_enquire_admin_availability_template_has_admin_callback
  - test_send_restaurant_order_confirmation_creates_accept_button
  - test_notify_ops_rider_alert_reaches_overwatch
  - test_notify_ops_rider_alert_picked_up_chases_the_delivery
  - test_notify_ops_rider_alert_survives_missing_overwatch_list
  - test_notify_rest_admins_rider_alert_heads_up_before_pickup
  - test_notify_rest_admins_rider_alert_chases_after_pickup
  - test_notify_rest_admins_rider_alert_picked_up_chases_the_delivery
  - test_notify_rest_admins_rider_alert_warns_and_continues_without_admins
  - test_notify_rest_admins_rider_alert_isolates_a_failing_admin
  - test_notify_rest_admins_rider_alert_dedupes_admin_numbers
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

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


def test_food_ready_y_callback_carries_order_number_within_button_payload_limit() -> None:
    """admin_order_reciept's food_ready_y callback (wa_senders.py:254-259) was changed from
    order_id to order_number so ordelo.delivery_progress.check_delivery_progress() can match
    on it directly, without reverse-engineering order_number from the order_id suffix.

    Mirrors the construction at that call site (rider_id, restaurant_name, order_number)
    rather than exercising the full admin_order_reciept, which needs a live DeliverySummary
    and RestaurantMaster. WhatsApp interactive button payloads are capped at 256 bytes; the
    swap is roughly size-neutral, but restaurant_name is the variable-length field, so this
    checks a long, realistic name stays inside budget.
    """
    long_restaurant_name = "The Great British Curry House & Tandoori Grill Restaurant"
    food_ready_y = wa_senders.CallbackButtonData(
        action="/AdminCollectionReady",
        rider_id="RIDER0123456789",
        restaurant_name=long_restaurant_name,
        order_number="ELAS-ABCDEFGH-999999",
    )
    payload = food_ready_y.model_dump()

    assert payload["order_number"] == "ELAS-ABCDEFGH-999999"
    assert "order_id" not in payload

    encoded = food_ready_y.model_dump_json().encode("utf-8")
    assert len(encoded) <= 256, (
        f"food_ready_y callback_data is {len(encoded)} bytes, over WhatsApp's 256-byte "
        "button payload limit"
    )


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


# %% notify_ops_rider_alert / notify_rest_admins_rider_alert


class _FakeWaLogger:
    """Stands in for WALogger, which fans out to the overwatch list."""

    def __init__(self) -> None:
        self.critical_calls: list[str] = []

    async def critical(self, text: str) -> None:
        self.critical_calls.append(text)


def _pickup_time_ago(minutes: float) -> str:
    """Pickup time `minutes` in the past. Callers stay off .5 boundaries because
    the senders round to whole minutes."""
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _pickup_time_in(minutes: float) -> str:
    """Pickup time `minutes` in the future. Same .5-boundary caveat as above."""
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _patch_wa_logger(monkeypatch) -> _FakeWaLogger:
    fake = _FakeWaLogger()

    async def _get():
        return fake

    monkeypatch.setattr(wa_senders, "get_wa_logger", _get)
    return fake


async def test_notify_ops_rider_alert_reaches_overwatch(
    monkeypatch, patch_async_wa_client: FakeAsyncWhatsApp
) -> None:
    wa_logger = _patch_wa_logger(monkeypatch)

    result = await wa_senders.notify_ops_rider_alert(
        phase="awaiting_pickup",
        order_number="ELAS-ABCD-1",
        pickup_time=_pickup_time_ago(11.2),
        rider_id="RIDER01",
        rider_name="Bas",
        rest_name="Elai",
        rest_ref="ELAS",
    )

    assert result == {"overwatch": "sent"}

    text = wa_logger.critical_calls[0]
    assert "has still not collected" in text
    assert "11 min past" in text
    assert "Elai" in text and "Bas" in text

    # Ops no longer messages restaurant admins directly.
    assert patch_async_wa_client.sent == []


async def test_notify_ops_rider_alert_picked_up_chases_the_delivery(
    monkeypatch, patch_async_wa_client: FakeAsyncWhatsApp
) -> None:
    wa_logger = _patch_wa_logger(monkeypatch)

    await wa_senders.notify_ops_rider_alert(
        phase="picked_up",
        order_number="ELAS-ABCD-1",
        pickup_time=_pickup_time_ago(31.2),
        rider_id="RIDER01",
        rider_name="Bas",
        rest_name="Elai",
    )

    text = wa_logger.critical_calls[0]
    assert "collected but has not delivered" in text
    assert "31 min past" in text
    assert "still not collected" not in text


async def test_notify_ops_rider_alert_survives_missing_overwatch_list(
    monkeypatch, patch_async_wa_client: FakeAsyncWhatsApp
) -> None:
    """get_overwatch_list() raises when the config row is absent. The exception must
    not escape -- the SQL has already marked the checkpoint sent, so an unhandled raise
    here would just be a noisier way of losing the same escalation."""

    async def _boom():
        raise ValueError("No config found for overwatch_list in ordelo_config")

    monkeypatch.setattr(wa_senders, "get_wa_logger", _boom)

    result = await wa_senders.notify_ops_rider_alert(
        phase="awaiting_pickup",
        order_number="ELAS-ABCD-1",
        pickup_time=_pickup_time_ago(11.2),
        rider_id="RIDER01",
    )

    assert result == {"overwatch": "failed"}


# %% notify_rest_admins_rider_alert


async def test_notify_rest_admins_rider_alert_heads_up_before_pickup(
    monkeypatch, patch_async_wa_client: FakeAsyncWhatsApp
) -> None:
    result = await wa_senders.notify_rest_admins_rider_alert(
        phase="awaiting_pickup",
        order_number="ELAS-ABCD-1",
        pickup_time=_pickup_time_in(9.8),
        rider_id="RIDER01",
        rider_name="Bas",
        rest_ref="ELAS",
        rest_admins=["ADMIN01", "ADMIN02"],
    )

    assert result == {"admins_notified": 2, "admins_failed": 0}

    admin_sends = [
        c for c in patch_async_wa_client.sent if c.kwargs["to"] in {"ADMIN01", "ADMIN02"}
    ]
    assert len(admin_sends) == 2
    text = admin_sends[0].kwargs["text"]
    assert "due to collect" in text
    assert "in ~10 min" in text
    assert "Please have it ready" in text
    assert all(c.kwargs["text"] == text for c in admin_sends)


async def test_notify_rest_admins_rider_alert_chases_after_pickup(
    monkeypatch, patch_async_wa_client: FakeAsyncWhatsApp
) -> None:
    result = await wa_senders.notify_rest_admins_rider_alert(
        phase="awaiting_pickup",
        order_number="ELAS-ABCD-1",
        pickup_time=_pickup_time_ago(6.2),
        rider_id="RIDER01",
        rider_name="Bas",
        rest_admins=["ADMIN01"],
    )

    assert result == {"admins_notified": 1, "admins_failed": 0}
    text = patch_async_wa_client.sent[0].kwargs["text"]
    assert "has not yet collected" in text
    assert "6 min past" in text
    assert "due to collect" not in text


async def test_notify_rest_admins_rider_alert_picked_up_chases_the_delivery(
    monkeypatch, patch_async_wa_client: FakeAsyncWhatsApp
) -> None:
    """This branch is config-disabled by default (rider_alert_to_rest_admins_delivery_intervals
    ships blank), so no runbook step and no normal traffic will ever exercise it. This
    unit test is the only thing standing there."""
    result = await wa_senders.notify_rest_admins_rider_alert(
        phase="picked_up",
        order_number="ELAS-ABCD-1",
        pickup_time=_pickup_time_ago(31.2),
        rider_id="RIDER01",
        rider_name="Bas",
        rest_admins=["ADMIN01"],
    )

    assert result == {"admins_notified": 1, "admins_failed": 0}
    text = patch_async_wa_client.sent[0].kwargs["text"]
    assert "collected but has not delivered" in text
    assert "31 min past" in text


async def test_notify_rest_admins_rider_alert_warns_and_continues_without_admins(
    monkeypatch, patch_async_wa_client: FakeAsyncWhatsApp
) -> None:
    result = await wa_senders.notify_rest_admins_rider_alert(
        phase="awaiting_pickup",
        order_number="ELAS-ABCD-1",
        pickup_time=_pickup_time_ago(11.2),
        rider_id="RIDER01",
        rest_ref="ELAS",
        rest_admins=None,
    )

    assert result == {"admins_notified": 0, "admins_failed": 0}
    assert patch_async_wa_client.sent == []


async def test_notify_rest_admins_rider_alert_isolates_a_failing_admin(
    monkeypatch, patch_async_wa_client: FakeAsyncWhatsApp
) -> None:
    original_send = patch_async_wa_client.send_message

    async def _flaky(**kwargs):
        if kwargs.get("to") == "ADMIN01":
            raise RuntimeError("bad number")
        return await original_send(**kwargs)

    monkeypatch.setattr(patch_async_wa_client, "send_message", _flaky)

    result = await wa_senders.notify_rest_admins_rider_alert(
        phase="awaiting_pickup",
        order_number="ELAS-ABCD-1",
        pickup_time=_pickup_time_ago(11.2),
        rider_id="RIDER01",
        rest_admins=["ADMIN01", "ADMIN02"],
    )

    assert result["admins_notified"] == 1
    assert result["admins_failed"] == 1


async def test_notify_rest_admins_rider_alert_dedupes_admin_numbers(
    monkeypatch, patch_async_wa_client: FakeAsyncWhatsApp
) -> None:
    result = await wa_senders.notify_rest_admins_rider_alert(
        phase="awaiting_pickup",
        order_number="ELAS-ABCD-1",
        pickup_time=_pickup_time_ago(11.2),
        rider_id="RIDER01",
        rest_admins=["ADMIN01", "ADMIN01", "", "ADMIN02"],
    )

    assert result == {"admins_notified": 2, "admins_failed": 0}
    assert len(patch_async_wa_client.sent) == 2
