"""Tests for the priority inbound WhatsApp current-location handler."""

from __future__ import annotations

from types import SimpleNamespace

from tests.fixtures.fake_wa import FakeAsyncWhatsApp, FakeMessage
from ordelo.agents.rider_threads import RiderThread
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


def _active_thread_factory(*, active: bool):
    """Stands in for rider_threads.active_for_rider (R2): the rider's one open thread, or None."""

    async def _active(_rider_id, touch=True):
        return RiderThread("ORDELO-dispatch-10", "RIDER01", dispatch_id=10) if active else None

    return _active


async def test_current_location_is_forwarded_and_acknowledged_via_agent(monkeypatch, patch_pg_pool) -> None:
    wa = FakeAsyncWhatsApp()
    msg = FakeMessage(sender="RIDER01", timestamp=1_700_000_000)
    msg.location = SimpleNamespace(
        current_location=True,
        latitude=51.5,
        longitude=-0.12,
    )
    msg.reply_to_message = SimpleNamespace(id="wamid.request")
    received = []
    agent_calls = []

    class _WaLocation:
        def __init__(self, **_kwargs):
            pass

        async def receive_whatsapp_location(self, receipt):
            received.append(receipt)
            return 1

    async def _fake_run(**kwargs):
        agent_calls.append(kwargs)

    monkeypatch.setattr(on_wa_location_handler, "WaLocation", _WaLocation)
    monkeypatch.setattr(on_wa_location_handler, "active_rider_thread", _active_thread_factory(active=True))
    monkeypatch.setattr(
        "ordelo.agents.agent_runner.run_rider_agent_w_custom_msg", _fake_run
    )

    await on_wa_location_handler.handle_wa_location_message(wa, msg)

    assert len(received) == 1
    assert received[0].rider_id == "RIDER01"
    assert received[0].reply_to_message_id == "wamid.request"
    assert received[0].latitude == 51.5
    assert wa.sent == []
    assert len(agent_calls) == 1
    assert agent_calls[0]["recipient"] == "RIDER01"
    assert agent_calls[0]["thread_id"] == "ORDELO-dispatch-10"
    assert "shared their current location" in agent_calls[0]["system_msg"]


async def test_uncorrelated_location_does_not_invoke_agent(monkeypatch, patch_pg_pool) -> None:
    wa = FakeAsyncWhatsApp()
    msg = FakeMessage(sender="RIDER01", timestamp=1_700_000_000)
    msg.location = SimpleNamespace(
        current_location=True,
        latitude=51.5,
        longitude=-0.12,
    )
    msg.reply_to_message = None
    agent_calls = []

    class _WaLocation:
        def __init__(self, **_kwargs):
            pass

        async def receive_whatsapp_location(self, receipt):
            return 0

    async def _fake_run(**kwargs):
        agent_calls.append(kwargs)

    monkeypatch.setattr(on_wa_location_handler, "WaLocation", _WaLocation)
    monkeypatch.setattr(on_wa_location_handler, "active_rider_thread", _active_thread_factory(active=True))
    monkeypatch.setattr(
        "ordelo.agents.agent_runner.run_rider_agent_w_custom_msg", _fake_run
    )

    await on_wa_location_handler.handle_wa_location_message(wa, msg)

    assert agent_calls == []


async def test_correlated_location_without_active_thread_skips_agent(monkeypatch, patch_pg_pool) -> None:
    """The rider was prompted via the direct-send fallback (no thread existed);
    the ack must not silently create one -- that would flip the request-side
    fallback decision for the rider's very next location ask."""
    wa = FakeAsyncWhatsApp()
    msg = FakeMessage(sender="RIDER01", timestamp=1_700_000_000)
    msg.location = SimpleNamespace(
        current_location=True,
        latitude=51.5,
        longitude=-0.12,
    )
    msg.reply_to_message = SimpleNamespace(id="wamid.request")
    agent_calls = []

    class _WaLocation:
        def __init__(self, **_kwargs):
            pass

        async def receive_whatsapp_location(self, receipt):
            return 1

    async def _fake_run(**kwargs):
        agent_calls.append(kwargs)

    monkeypatch.setattr(on_wa_location_handler, "WaLocation", _WaLocation)
    monkeypatch.setattr(on_wa_location_handler, "active_rider_thread", _active_thread_factory(active=False))
    monkeypatch.setattr(
        "ordelo.agents.agent_runner.run_rider_agent_w_custom_msg", _fake_run
    )

    await on_wa_location_handler.handle_wa_location_message(wa, msg)

    assert agent_calls == []
