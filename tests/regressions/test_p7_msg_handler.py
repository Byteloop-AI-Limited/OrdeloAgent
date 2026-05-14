"""P7 on_message_wa_handler uncovered utility coverage."""
from __future__ import annotations
from datetime import datetime, timezone
from types import SimpleNamespace
from tests.fixtures.fake_wa import FakeAsyncWhatsApp, FakeMessage
from watomation import on_message_wa_handler as h


def test_message_time_uk_datetime():
    msg = SimpleNamespace(timestamp=datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc))
    r = h._message_time_uk(msg)
    assert r is not None


def test_message_time_uk_timestamp_ms():
    msg = SimpleNamespace(timestamp=None, timestamp_ms=1746792000000)
    r = h._message_time_uk(msg)
    assert r is not None


def test_message_time_uk_timestamp_s():
    msg = SimpleNamespace(timestamp=None, timestamp_ms=1746792000)
    r = h._message_time_uk(msg)
    assert r is not None


def test_message_time_uk_none():
    msg = SimpleNamespace(timestamp=None, timestamp_ms=None)
    assert h._message_time_uk(msg) is None


def test_is_outside_service_hours_false():
    msg = SimpleNamespace(timestamp=datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc))
    assert h.is_outside_service_hours(None, msg) is False


def test_is_outside_service_hours_true():
    msg = SimpleNamespace(timestamp=datetime(2026, 5, 9, 3, 0, tzinfo=timezone.utc))
    assert h.is_outside_service_hours(None, msg) is True


async def test_send_closed_message(fake_async_wa: FakeAsyncWhatsApp):
    msg = FakeMessage(sender="4474")
    await h.send_closed_message(fake_async_wa, msg)
    assert "closed" in fake_async_wa.sent[-1].kwargs["text"]


async def test_live_location_no_inflight(fake_async_wa: FakeAsyncWhatsApp, patch_supabase_client, patch_pg_pool):
    from tests.fixtures.fake_supabase import FakeSupabaseResponse
    patch_supabase_client.register(table="delivery_inflight", verb="select", response=FakeSupabaseResponse(data=[]))
    await h.live_location(fake_async_wa, FakeMessage(sender="4474"))
    assert "no active delivery" in fake_async_wa.sent[-1].kwargs["text"]


async def test_clear_dispatch(fake_async_wa: FakeAsyncWhatsApp, patch_supabase_client):
    patch_supabase_client.register_rpc("clear_dispatch", SimpleNamespace(data={"ok": True}))
    await h.clear_dispatch(fake_async_wa, FakeMessage(sender="4474"))
    assert patch_supabase_client.rpc_calls[-1].payload["name"] == "clear_dispatch"


async def test_test_flow(fake_sync_wa, monkeypatch):
    monkeypatch.setattr(h, "_sync_wa_client", fake_sync_wa)
    await h.test_flow(fake_sync_wa, FakeMessage(sender="4474"))
    s = fake_sync_wa.sent[-1]
    assert s.kwargs["buttons"].flow_id == 955259853427256


def test_handle_callback_button():
    h.handle_callback_button(None, SimpleNamespace(data={"x": 1}))


def test_on_sign_up_request():
    r = h.on_sign_up_request(None, SimpleNamespace(has_error=False, version="3.0", data={}))
    assert r.screen == "START"


def test_on_sign_up_request_error():
    r = h.on_sign_up_request(None, SimpleNamespace(has_error=True, version="3.0", data={}))
    assert r.data == {"acknowledged": True}


async def test_init_delivery_summary(patch_supabase_client):
    patch_supabase_client.register_rpc("init_delivery", SimpleNamespace(data={"ok": True}))
    await h.init_delivery_summary("ELAS-ABCD-1", "4474")
    assert patch_supabase_client.rpc_calls[-1].payload["name"] == "init_delivery"


async def test_process_wa_msg_end_shift_intent(monkeypatch, patch_pg_pool, patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp):
    from tests.fixtures.fake_supabase import FakeSupabaseResponse
    patch_supabase_client.register(table="rider_master", verb="select", response=FakeSupabaseResponse(data=[{"is_in_shift": True}]))
    async def _no_thread(self, r): return None
    monkeypatch.setattr(
        h,
        "ThreadHandler",
        type("TH", (), {"__init__": lambda self, pool: None, "get_active_thread": _no_thread}),
    )
    monkeypatch.setattr(h, "get_rider_intent", lambda text: SimpleNamespace(intent="End Shift", confidence=0.9))
    calls = []
    async def _fake_enquire(wa, msg): calls.append(msg.sender)
    monkeypatch.setattr(h, "enquire_shift_availability_non_template", _fake_enquire)
    await h.process_wa_msg(fake_async_wa, FakeMessage(sender="RIDER01", text="end"))
    assert calls == ["RIDER01"]
