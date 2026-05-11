"""Tests for WhatsApp inbound message handlers.

These tests call handler functions directly with fake WhatsApp messages, fake
Supabase responses, and patched graph/thread helpers so no external WhatsApp,
LLM, DB, or network access is required.

Key Functions:
  - test_process_wa_msg_not_in_shift_enquires_availability
  - test_process_wa_msg_in_shift_without_thread_sends_no_active_delivery
  - test_process_wa_msg_with_active_thread_runs_rider_graph
  - test_send_live_map_location_handles_no_inflight_missing_and_success
  - test_reset_thread_closes_dispatch_and_thread
  - test_test_delivery_schedules_init_and_updates_summary
"""

from __future__ import annotations

from types import SimpleNamespace

from watomation import on_message_wa_handler as handler
from tests.fixtures.fake_supabase import FakeSupabaseResponse
from tests.fixtures.fake_wa import FakeAsyncWhatsApp, FakeMessage


class _FakeThreadHandler:
    active_thread = None
    inactive_calls = []

    def __init__(self, pool):
        self.pool = pool

    async def get_active_thread(self, recipient):
        return self.active_thread

    async def make_threads_inactive(self, recipient):
        self.inactive_calls.append(recipient)
        return {"message": "closed"}


async def test_process_wa_msg_not_in_shift_enquires_availability(monkeypatch, patch_pg_pool, patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp) -> None:
    patch_supabase_client.register(table="rider_master", verb="select", response=FakeSupabaseResponse(data=[{"is_in_shift": False}]))
    monkeypatch.setattr(handler, "ThreadHandler", _FakeThreadHandler)
    calls = []

    async def _fake_enquire(wa, msg):
        calls.append((wa, msg.sender))

    monkeypatch.setattr(handler, "enquire_shift_availability_non_template", _fake_enquire)

    await handler.process_wa_msg(fake_async_wa, FakeMessage(sender="RIDER01", text="hello"))

    assert calls == [(fake_async_wa, "RIDER01")]


async def test_process_wa_msg_in_shift_without_thread_sends_no_active_delivery(monkeypatch, patch_pg_pool, patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp) -> None:
    _FakeThreadHandler.active_thread = None
    patch_supabase_client.register(table="rider_master", verb="select", response=FakeSupabaseResponse(data=[{"is_in_shift": True}]))
    monkeypatch.setattr(handler, "ThreadHandler", _FakeThreadHandler)
    monkeypatch.setattr(handler, "get_rider_intent", lambda text: SimpleNamespace(intent="SomethingElse", confidence=0.9))

    await handler.process_wa_msg(fake_async_wa, FakeMessage(sender="RIDER01", text="hello"))

    assert fake_async_wa.sent[-1].kwargs == {"to": "RIDER01", "text": "You have no active delivery"}


async def test_process_wa_msg_with_active_thread_runs_rider_graph(monkeypatch, patch_pg_pool, patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp) -> None:
    _FakeThreadHandler.active_thread = {"thread_id": "thread-1"}
    patch_supabase_client.register(table="rider_master", verb="select", response=FakeSupabaseResponse(data=[{"is_in_shift": True}]))
    monkeypatch.setattr(handler, "ThreadHandler", _FakeThreadHandler)
    calls = []

    async def _fake_run(recipient, human_msg=None, state_update_dict=None, **kwargs):
        calls.append({"recipient": recipient, "human_msg": human_msg, "state_update_dict": state_update_dict, **kwargs})

    monkeypatch.setattr(handler, "run_rider_agent_w_custom_msg", _fake_run)
    msg = FakeMessage(sender="RIDER01", text="code 11")

    await handler.process_wa_msg(fake_async_wa, msg)

    assert calls == [{"recipient": "RIDER01", "human_msg": "code 11", "state_update_dict": {"latest_wa_msg_id": msg.id}}]


async def test_send_live_map_location_handles_no_inflight_missing_and_success(monkeypatch, patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp) -> None:
    patch_supabase_client.register(table="delivery_inflight", verb="select", response=FakeSupabaseResponse(data=[]))
    await handler.send_live_map_location(fake_async_wa, FakeMessage(sender="RIDER01"))
    assert fake_async_wa.sent[-1].kwargs["text"] == "Location not available. You have no active delivery"

    patch_supabase_client.register(table="delivery_inflight", verb="select", response=FakeSupabaseResponse(data=[{"order_number": "ELAS-ABCD-1"}]))

    async def _base_url(rest_ref):
        return "https://rest.example.com"

    monkeypatch.setattr(handler, "get_restaurant_base_url_async", _base_url)

    async def _none_location(order_number):
        return None

    monkeypatch.setattr(handler, "get_live_map_location_url", _none_location)
    await handler.send_live_map_location(fake_async_wa, FakeMessage(sender="RIDER01"))
    assert fake_async_wa.sent[-1].kwargs["text"] == "Live map location not available"

    async def _some_location(order_number):
        return "https://maps.example.com"

    monkeypatch.setattr(handler, "get_live_map_location_url", _some_location)
    await handler.send_live_map_location(fake_async_wa, FakeMessage(sender="RIDER01"))
    assert fake_async_wa.sent[-1].kwargs["text"] == "https://rest.example.com/location-hooks/live-location-map/ELAS-ABCD-1"


async def test_reset_thread_closes_dispatch_and_thread(monkeypatch, patch_pg_pool, patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp) -> None:
    _FakeThreadHandler.inactive_calls = []
    patch_supabase_client.register(table="delivery_inflight", verb="select", response=FakeSupabaseResponse(data=[{"dispatch_id": 10}]))
    patch_supabase_client.register_rpc("dispatch_complete_func", FakeSupabaseResponse(data={"ok": True}))
    monkeypatch.setattr(handler, "ThreadHandler", _FakeThreadHandler)

    await handler.reset_thread(fake_async_wa, FakeMessage(sender="RIDER01"))

    assert patch_supabase_client.rpc_calls[-1].payload == {"name": "dispatch_complete_func", "args": {"p_dispatch_id": 10}}
    assert _FakeThreadHandler.inactive_calls == ["RIDER01"]
    assert fake_async_wa.sent[-1].kwargs["text"] == "Starting new conversation"


async def test_test_delivery_schedules_init_and_updates_summary(monkeypatch, patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp) -> None:
    patch_supabase_client.register_rpc("cleanup_delivery_order", FakeSupabaseResponse(data={"ok": True}))
    patch_supabase_client.register(table="delivery_summary", verb="update", response=FakeSupabaseResponse(data=[{"ok": True}]))
    tasks = []

    def _fake_create_task(coro):
        tasks.append(coro)
        coro.close()
        return SimpleNamespace(cancel=lambda: None)

    monkeypatch.setattr(handler.asyncio, "create_task", _fake_create_task)

    result = await handler.test_delivery(fake_async_wa, FakeMessage(sender="RIDER01"))

    assert result == {"status": "success"}
    assert patch_supabase_client.rpc_calls[-1].payload["name"] == "cleanup_delivery_order"
    assert patch_supabase_client.calls[-1].payload == {"status": "unassigned"}
    assert len(tasks) == 1
