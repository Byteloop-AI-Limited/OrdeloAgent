"""Tests for the priority inbound WhatsApp current-location handler."""

from __future__ import annotations

from types import SimpleNamespace

from tests.fixtures.fake_wa import FakeAsyncWhatsApp, FakeMessage
from watomation import on_wa_location_handler


async def test_manual_pin_is_rejected_without_calling_wa_location(monkeypatch) -> None:
    wa = FakeAsyncWhatsApp()
    msg = FakeMessage(sender="RIDER01")
    msg.location = SimpleNamespace(
        current_location=False,
        latitude=51.5,
        longitude=-0.12,
    )

    class _UnexpectedWaLocation:
        def __init__(self, **_kwargs):
            raise AssertionError("manual pins must not enter WaLocation")

    monkeypatch.setattr(on_wa_location_handler, "WaLocation", _UnexpectedWaLocation)

    await on_wa_location_handler.handle_wa_location_message(wa, msg)

    assert wa.sent[-1].method == "send_message"
    assert "Share current location" in wa.sent[-1].kwargs["text"]


async def test_current_location_is_forwarded_with_reply_correlation(monkeypatch) -> None:
    wa = FakeAsyncWhatsApp()
    msg = FakeMessage(sender="RIDER01", timestamp=1_700_000_000)
    msg.location = SimpleNamespace(
        current_location=True,
        latitude=51.5,
        longitude=-0.12,
    )
    msg.reply_to_message = SimpleNamespace(id="wamid.request")
    received = []

    class _WaLocation:
        def __init__(self, **_kwargs):
            pass

        async def receive_whatsapp_location(self, receipt):
            received.append(receipt)
            return 1

    monkeypatch.setattr(on_wa_location_handler, "WaLocation", _WaLocation)

    await on_wa_location_handler.handle_wa_location_message(wa, msg)

    assert len(received) == 1
    assert received[0].rider_id == "RIDER01"
    assert received[0].reply_to_message_id == "wamid.request"
    assert received[0].latitude == 51.5
    assert wa.sent == []
