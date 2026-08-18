"""Tests for rider agent tools and routing nodes.

The tools are called directly with simple runtime/context fakes, avoiding a real
LangGraph/checkpointer while still exercising DB, WA, and Command updates.

Key Functions:
  - test_notify_pickup_time_adjusted_sends_message
  - test_notify_pickup_time_adjusted_no_pickup_time
  - test_send_pickup_and_dropoff_location_send_whatsapp_locations
  - test_send_start_live_tracking_link_sends_button_url
  - test_cancel_delivery_before_pickup_calls_rpc_and_sets_awaiting_reason
  - test_capture_reason_for_cancel_before_pickup_updates_dispatch
  - test_verify_restaurant_confirmation_code_wrong_and_success_paths
  - test_verify_customer_confirmation_code_wrong_path
  - test_terminate_delivery_job_records_cancel_reason_and_closes_thread
  - test_request_rider_current_location_sends_intro_and_request_and_records_id
  - test_request_rider_current_location_noop_without_pending_request
  - test_request_rider_current_location_marks_failed_on_send_error
  - test_agent_node_routes_awaiting_cancel_reason_tool_and_human_messages
  - test_agent_node_forces_location_tool_call_when_flagged
  - test_respond_node_sends_last_ai_message
"""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END

from ordelo.agents import rider_agent
from tests.fixtures.fake_supabase import FakeSupabaseResponse
from tests.fixtures.fake_wa import FakeAsyncWhatsApp


def _runtime(*, client, wa, recipient="RIDER01"):
    return SimpleNamespace(context=SimpleNamespace(client_ordelo=client, wa_client=wa, recipient=recipient))


def _summary_row(**overrides):
    row = {
        "order_number": "ELAS-ABCD-1",
        "rest_name": "Elai",
        "rest_lat": 51.5074,
        "rest_lon": -0.1278,
        "rest_address": "1 Test Street",
        "customer_lat": 51.5174,
        "customer_lon": -0.1378,
        "customer_address": "2 Customer Road",
        "customer_id": "447400000000",
        "rest_confirmation_code": 11,
        "cust_confirmation_code": 22,
    }
    row.update(overrides)
    return row


async def test_notify_pickup_time_adjusted_sends_message(fake_async_wa: FakeAsyncWhatsApp, patch_supabase_client) -> None:
    result = await rider_agent.notify_pickup_time_adjusted(
        {
            "rider_name": "Bas",
            "order_number": "ELAS-ABCD-1",
            "reply_to_msg_id": "msg-1",
            "pickup_time": "2026-05-09T11:40:00+00:00",
        },
        "tool-1",
        _runtime(client=patch_supabase_client, wa=fake_async_wa),
    )

    sent = fake_async_wa.sent[-1]
    assert sent.kwargs["to"] == "RIDER01"
    assert "updated" in sent.kwargs["text"]
    assert isinstance(result.update["messages"][-1], AIMessage)
    assert "/dontRespond" in result.update["messages"][-1].content


async def test_notify_pickup_time_adjusted_no_pickup_time(fake_async_wa: FakeAsyncWhatsApp, patch_supabase_client) -> None:
    result = await rider_agent.notify_pickup_time_adjusted(
        {"rider_name": "Bas", "order_number": "ELAS-ABCD-1", "pickup_time": None},
        "tool-1",
        _runtime(client=patch_supabase_client, wa=fake_async_wa),
    )

    assert fake_async_wa.sent == []
    assert "/dontRespond" in result.update["messages"][-1].content


async def test_send_pickup_and_dropoff_location_send_whatsapp_locations(patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp) -> None:
    patch_supabase_client.register(table="delivery_summary", verb="select", response=FakeSupabaseResponse(data=[_summary_row()]))
    runtime = _runtime(client=patch_supabase_client, wa=fake_async_wa)

    pickup = await rider_agent.send_pickup_location({"order_number": "ELAS-ABCD-1", "reply_to_msg_id": "msg-1"}, "tool-1", runtime)
    dropoff = await rider_agent.send_dropoff_location({"order_number": "ELAS-ABCD-1", "reply_to_msg_id": "msg-1"}, "tool-2", runtime)

    assert pickup.update["messages"][0].content == "Pickup location sent to user."
    assert dropoff.update["messages"][0].content == "Dropoff location sent to user."
    assert fake_async_wa.sent[0].method == "send_location"
    assert fake_async_wa.sent[0].kwargs["latitude"] == 51.5074
    assert fake_async_wa.sent[1].kwargs["latitude"] == 51.5174
    assert fake_async_wa.sent[2].method == "send_message"


async def test_send_start_live_tracking_link_sends_button_url(fake_async_wa: FakeAsyncWhatsApp, patch_supabase_client) -> None:
    result = await rider_agent.send_start_live_tracking_link(
        {"start_live_tracking_url": "https://track.example.com/start", "reply_to_msg_id": "msg-1"},
        "tool-1",
        _runtime(client=patch_supabase_client, wa=fake_async_wa),
    )

    sent = fake_async_wa.sent[-1]
    assert sent.kwargs["header"] == "Enable Live Tracking"
    assert sent.kwargs["buttons"].url == "https://track.example.com/start"
    assert "live location tracking" in result.update["messages"][0].content


def test_legacy_start_tracking_helper_is_not_exposed_to_the_rider_agent() -> None:
    assert rider_agent.send_start_live_tracking_link not in rider_agent._rider_agent_tools


async def test_cancel_delivery_before_pickup_calls_rpc_and_sets_awaiting_reason(patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp) -> None:
    patch_supabase_client.register_rpc("dispatch_cancel_before_pickup", FakeSupabaseResponse(data={"ok": True}))

    result = await rider_agent.cancel_delivery_before_pickup(
        {"dispatch_id": 10, "order_number": "ELAS-ABCD-1", "rider_name": "Bas"},
        "tool-1",
        _runtime(client=patch_supabase_client, wa=fake_async_wa),
    )

    assert result.update["awaiting_cancel_reason"] is True
    assert "Ok Bas" in result.update["messages"][0].content
    assert patch_supabase_client.rpc_calls[-1].payload == {"name": "dispatch_cancel_before_pickup", "args": {"p_dispatch_id": 10}}


async def test_capture_reason_for_cancel_before_pickup_updates_dispatch(patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp) -> None:
    patch_supabase_client.register(table="delivery_dispatch", verb="update", response=FakeSupabaseResponse(data=[{"ok": True}]))

    result = await rider_agent.capture_reason_for_cancel_before_pickup(
        "Bike puncture",
        {"dispatch_id": 10, "order_number": "ELAS-ABCD-1"},
        "tool-1",
        _runtime(client=patch_supabase_client, wa=fake_async_wa),
    )

    assert result.update["awaiting_cancel_reason"] is False
    assert patch_supabase_client.calls[-1].payload["reason_for_decline"] == "Bike puncture"


async def test_verify_restaurant_confirmation_code_wrong_and_success_paths(monkeypatch, patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp) -> None:
    patch_supabase_client.register(table="delivery_summary", verb="select", response=FakeSupabaseResponse(data=[_summary_row()]))
    patch_supabase_client.register(table="delivery_dispatch", verb="update", response=FakeSupabaseResponse(data=[{"ok": True}]))
    webhook_calls = []
    observations = []

    async def _fake_rest_webhook(order_number, customer_id):
        webhook_calls.append((order_number, customer_id))

    class _Logger:
        async def info(self, message):
            webhook_calls.append(("log", message))

    async def _fake_wa_logger():
        return _Logger()

    class _FakeWaLocation:
        def __init__(self, *, wa_client):
            self.wa_client = wa_client

        async def observe_restaurant_confirmation(self, observation):
            observations.append(observation)
            return 0

    monkeypatch.setattr(rider_agent, "post_rider_event_restaurant_cc", _fake_rest_webhook)
    monkeypatch.setattr(rider_agent, "get_wa_logger", _fake_wa_logger)
    monkeypatch.setattr(rider_agent, "WaLocation", _FakeWaLocation)
    state = {"dispatch_id": 10, "order_number": "ELAS-ABCD-1", "latest_wa_msg_id": "wa-msg"}
    runtime = _runtime(client=patch_supabase_client, wa=fake_async_wa)

    wrong = await rider_agent.verify_restaurant_confirmation_code(99, state, "tool-1", runtime)
    assert "Wrong *restaurant*" in wrong.update["messages"][0].content
    assert fake_async_wa.sent[-1].kwargs["emoji"] == "❌"

    success = await rider_agent.verify_restaurant_confirmation_code(11, state, "tool-2", runtime)
    assert success.update["is_restaurant_confirmation_code_verified"] is True
    assert ("ELAS-ABCD-1", "447400000000") in webhook_calls
    assert observations[0].latitude == 51.5074
    assert observations[0].longitude == -0.1278
    assert patch_supabase_client.calls[-1].payload["status"] == "pickedup"


async def test_verify_customer_confirmation_code_wrong_path(patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp) -> None:
    patch_supabase_client.register(table="delivery_summary", verb="select", response=FakeSupabaseResponse(data=[_summary_row()]))

    result = await rider_agent.verify_customer_confirmation_code(
        99,
        {"dispatch_id": 10, "order_number": "ELAS-ABCD-1", "latest_wa_msg_id": "wa-msg"},
        "tool-1",
        _runtime(client=patch_supabase_client, wa=fake_async_wa),
    )

    assert "Wrong *customer*" in result.update["messages"][0].content
    assert fake_async_wa.sent[-1].kwargs["emoji"] == "❌"


async def test_terminate_delivery_job_records_cancel_reason_and_closes_thread(monkeypatch, patch_pg_pool, patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp) -> None:
    patch_pg_pool.register_sql("make_threads_inactive", [(1,)])
    patch_supabase_client.register(table="delivery_dispatch", verb="update", response=FakeSupabaseResponse(data=[{"ok": True}]))

    result = await rider_agent.terminate_delivery_job(
        {"dispatch_id": 10, "awaiting_cancel_reason": True, "reply_to_msg_id": "msg-1"},
        "tool-1",
        _runtime(client=patch_supabase_client, wa=fake_async_wa),
        reason_for_decline="Bike puncture",
    )

    assert result.update["awaiting_cancel_reason"] is False
    assert patch_supabase_client.calls[-1].payload["reason_for_decline"] == "Bike puncture"
    assert fake_async_wa.sent[-1].kwargs["text"] == "Delivery job completed ✅, thank you."
    assert "buttons" not in fake_async_wa.sent[-1].kwargs


async def test_request_rider_current_location_sends_intro_and_request_and_records_id(
    monkeypatch, patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp
) -> None:
    recorded = []

    class _FakeWaLocation:
        def __init__(self, *, wa_client):
            self.wa_client = wa_client

        async def record_prompt_sent(self, request_id, message_id):
            recorded.append((request_id, message_id))

        async def mark_prompt_failed(self, request_id, reason):
            raise AssertionError("mark_prompt_failed should not be called on success")

    monkeypatch.setattr(rider_agent, "WaLocation", _FakeWaLocation)

    result = await rider_agent.request_rider_current_location(
        "Your customer is asking where you are.",
        {"wa_location_request_id": "req-1"},
        "tool-1",
        _runtime(client=patch_supabase_client, wa=fake_async_wa),
    )

    assert fake_async_wa.sent[0].method == "send_message"
    assert fake_async_wa.sent[0].kwargs["text"] == "Your customer is asking where you are."
    assert fake_async_wa.sent[1].method == "request_location"
    assert recorded[0][0] == "req-1"
    assert result.update["wa_location_request_id"] is None
    assert result.update["force_wa_location_prompt"] is False
    assert "/dontRespond" in result.update["messages"][-1].content


async def test_request_rider_current_location_noop_without_pending_request(
    patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp
) -> None:
    result = await rider_agent.request_rider_current_location(
        "Your customer is asking where you are.",
        {},
        "tool-1",
        _runtime(client=patch_supabase_client, wa=fake_async_wa),
    )

    assert fake_async_wa.sent == []
    assert "No pending location request" in result.update["messages"][0].content


async def test_request_rider_current_location_marks_failed_on_send_error(
    monkeypatch, patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp
) -> None:
    failed = []

    class _FakeWaLocation:
        def __init__(self, *, wa_client):
            self.wa_client = wa_client

        async def record_prompt_sent(self, request_id, message_id):
            raise AssertionError("record_prompt_sent should not be called on failure")

        async def mark_prompt_failed(self, request_id, reason):
            failed.append((request_id, reason))

    async def _boom(**_kwargs):
        raise RuntimeError("wa down")

    monkeypatch.setattr(rider_agent, "WaLocation", _FakeWaLocation)
    monkeypatch.setattr(fake_async_wa, "request_location", _boom)

    result = await rider_agent.request_rider_current_location(
        "Your customer is asking where you are.",
        {"wa_location_request_id": "req-1"},
        "tool-1",
        _runtime(client=patch_supabase_client, wa=fake_async_wa),
    )

    assert failed == [("req-1", "RuntimeError")]
    assert result.update["wa_location_request_id"] is None
    assert "Failed to send" in result.update["messages"][0].content


def test_agent_node_routes_awaiting_cancel_reason_tool_and_human_messages() -> None:
    tool_result = rider_agent.agent_node({"awaiting_cancel_reason": True, "messages": [ToolMessage("Why?", tool_call_id="tool-1")]})
    assert tool_result.goto == "respondNode"
    assert tool_result.update["messages"][0].content == "Why?"

    human_result = rider_agent.agent_node({"awaiting_cancel_reason": True, "messages": [HumanMessage("Bike puncture")]})
    assert human_result.goto == "toolNode"
    call = human_result.update["messages"][0].tool_calls[0]
    assert call["name"] == "terminate_delivery_job"
    assert call["args"] == {"reason_for_decline": "Bike puncture"}

    end_result = rider_agent.agent_node({"messages": [AIMessage("done")]})
    assert end_result.goto == END


def test_agent_node_forces_location_tool_call_when_flagged() -> None:
    # Preceded by a plain AIMessage, mirroring the state after the LLM missed
    # the tool -- the deterministic branch must still fire, not hit the
    # trailing-AIMessage END guard.
    result = rider_agent.agent_node(
        {
            "force_wa_location_prompt": True,
            "wa_location_request_id": "req-1",
            "messages": [AIMessage("some earlier reply")],
        }
    )

    assert result.goto == "toolNode"
    call = result.update["messages"][0].tool_calls[0]
    assert call["name"] == "request_rider_current_location"
    assert "intro_message" in call["args"]


async def test_respond_node_sends_last_ai_message(patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp) -> None:
    result = await rider_agent.respond_node(
        {"reply_to_msg_id": "msg-1", "messages": [AIMessage("Hello rider")]},
        _runtime(client=patch_supabase_client, wa=fake_async_wa),
    )

    assert result.goto == END
    assert fake_async_wa.sent[-1].kwargs == {"to": "RIDER01", "text": "Hello rider", "reply_to_message_id": "msg-1"}
