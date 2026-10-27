"""Tests for rider agent tools and routing nodes.

The tools are called directly with simple runtime/context fakes, avoiding a real
LangGraph/checkpointer while still exercising DB, WA, and Command updates.

Key Functions:
  - test_notify_pickup_time_adjusted_sends_message
  - test_notify_pickup_time_adjusted_no_pickup_time
  - test_notify_pickup_reminder_before_pickup_uses_real_minutes_not_the_offset
  - test_notify_pickup_reminder_past_pickup_warns_rider
  - test_notify_pickup_reminder_without_offset_cue_sends_nothing
  - test_notify_pickup_reminder_no_pickup_time
  - test_notify_pickup_reminder_in_transit_chases_the_delivery
  - test_notify_pickup_reminder_clears_phase_with_offset
  - test_notify_pickup_reminder_in_transit_never_claims_a_future_time_has_passed
  - test_notify_pickup_reminder_accepts_a_datetime_from_graph_state
  - test_notify_pickup_reminder_accepts_a_naive_datetime_from_graph_state
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

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END

from ordelo.agents import rider_agent
from ordelo.rider_messaging.whatsapp import WhatsAppRiderMessenger
from tests.fixtures.fake_supabase import FakeSupabaseResponse
from tests.fixtures.fake_wa import FakeAsyncWhatsApp


def _runtime(*, client, wa, recipient="RIDER01", thread_id="ORDELO-dispatch-10"):
    """The tools talk through ctx.messenger since R3. The WhatsApp adapter around the fake pywa client proves the
    rider still gets exactly the same WhatsApp calls (every assertion below is on fake_async_wa)."""
    return SimpleNamespace(context=SimpleNamespace(
        client_ordelo=client, messenger=WhatsAppRiderMessenger(wa, recipient), recipient=recipient,
        thread_id=thread_id, dispatch_id=10,
    ))


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


def _pickup_time_in(minutes: float) -> str:
    """Pickup time `minutes` from now. Keep callers off .5 boundaries: the tool
    rounds to whole minutes, and a boundary value can flip the before/after
    branch under a slow test run."""
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


async def test_notify_pickup_reminder_accepts_a_datetime_from_graph_state(
    fake_async_wa: FakeAsyncWhatsApp, patch_supabase_client
) -> None:
    """State holds pickup_time as a datetime on the normal path, not an ISO string.

    init_ordelo_graph (agent_runner.py) writes DeliverySummary.pickup_time, typed
    Optional[datetime]. Parsing that with parse_db_iso raises TypeError, ToolNode
    swallows it, and the router still logs "Pickup alert sent" while the SQL has
    already marked the checkpoint sent -- the alert is lost for good. Every other
    test here passes a string, which is why the suite was green while the normal
    path was broken.
    """
    result = await rider_agent.notify_pickup_reminder(
        {
            "rider_name": "Bas",
            "order_number": "ELAS-ABCD-1",
            "pickup_time": datetime.now(timezone.utc) + timedelta(minutes=4.2),
            "pickup_alert_offset": -5,
        },
        "tool-1",
        _runtime(client=patch_supabase_client, wa=fake_async_wa),
    )

    assert fake_async_wa.sent, "a datetime in state must still produce a message"
    assert "in about 4 min" in fake_async_wa.sent[-1].kwargs["text"]
    assert result.update["pickup_alert_offset"] is None


async def test_notify_pickup_reminder_accepts_a_naive_datetime_from_graph_state(
    fake_async_wa: FakeAsyncWhatsApp, patch_supabase_client
) -> None:
    """to_utc_aware promises a naive value is treated as UTC, so the subtraction
    against an aware now() cannot raise 'can't subtract offset-naive and
    offset-aware datetimes'."""
    naive_pickup = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=7.2)

    await rider_agent.notify_pickup_reminder(
        {
            "rider_name": "Bas",
            "order_number": "ELAS-ABCD-1",
            "pickup_time": naive_pickup,
            "pickup_alert_offset": 5,
        },
        "tool-1",
        _runtime(client=patch_supabase_client, wa=fake_async_wa),
    )

    assert "7 min past the pickup time" in fake_async_wa.sent[-1].kwargs["text"]


async def test_notify_pickup_reminder_before_pickup_uses_real_minutes_not_the_offset(
    fake_async_wa: FakeAsyncWhatsApp, patch_supabase_client
) -> None:
    """The -5 checkpoint can fire at 1 minute to pickup; the text must say 1, not 5."""
    result = await rider_agent.notify_pickup_reminder(
        {
            "rider_name": "Bas",
            "order_number": "ELAS-ABCD-1",
            "reply_to_msg_id": "msg-1",
            # 1.2 min sits mid-bucket (0.5..1.5 rounds to 1), so elapsed test
            # time cannot tip this onto a rounding boundary and flip the branch.
            "pickup_time": _pickup_time_in(1.2),
            "pickup_alert_offset": -5,
        },
        "tool-1",
        _runtime(client=patch_supabase_client, wa=fake_async_wa),
    )

    text = fake_async_wa.sent[-1].kwargs["text"]
    assert "in about" in text and "past the pickup time" not in text
    assert "in about 1 min" in text
    assert "5 min" not in text
    # The cue is cleared so a later, unrelated turn cannot re-fire the alert.
    assert result.update["pickup_alert_offset"] is None


async def test_notify_pickup_reminder_past_pickup_warns_rider(
    fake_async_wa: FakeAsyncWhatsApp, patch_supabase_client
) -> None:
    await rider_agent.notify_pickup_reminder(
        {
            "rider_name": "Bas",
            "order_number": "ELAS-ABCD-1",
            "pickup_time": _pickup_time_in(-7.2),
            "pickup_alert_offset": 5,
        },
        "tool-1",
        _runtime(client=patch_supabase_client, wa=fake_async_wa),
    )

    text = fake_async_wa.sent[-1].kwargs["text"]
    assert "past the pickup time" in text and "in about" not in text
    assert "7 min past the pickup time" in text


async def test_notify_pickup_reminder_without_offset_cue_sends_nothing(
    fake_async_wa: FakeAsyncWhatsApp, patch_supabase_client
) -> None:
    """Guards against the LLM calling this on its own initiative."""
    result = await rider_agent.notify_pickup_reminder(
        {
            "rider_name": "Bas",
            "order_number": "ELAS-ABCD-1",
            "pickup_time": _pickup_time_in(3),
        },
        "tool-1",
        _runtime(client=patch_supabase_client, wa=fake_async_wa),
    )

    assert fake_async_wa.sent == []
    assert "/dontRespond" in result.update["messages"][-1].content


async def test_notify_pickup_reminder_no_pickup_time(
    fake_async_wa: FakeAsyncWhatsApp, patch_supabase_client
) -> None:
    result = await rider_agent.notify_pickup_reminder(
        {"rider_name": "Bas", "order_number": "ELAS-ABCD-1", "pickup_time": None, "pickup_alert_offset": 2},
        "tool-1",
        _runtime(client=patch_supabase_client, wa=fake_async_wa),
    )

    assert fake_async_wa.sent == []
    assert result.update["pickup_alert_offset"] is None


async def test_notify_pickup_reminder_in_transit_chases_the_delivery(
    fake_async_wa: FakeAsyncWhatsApp, patch_supabase_client
) -> None:
    """picked_up phase must chase the delivery, not send the rider to collect again."""
    await rider_agent.notify_pickup_reminder(
        {
            "rider_name": "Bas",
            "order_number": "ELAS-ABCD-1",
            "pickup_time": _pickup_time_in(-31.2),
            "pickup_alert_offset": 30,
            "pickup_alert_phase": "picked_up",
        },
        "tool-1",
        _runtime(client=patch_supabase_client, wa=fake_async_wa),
    )

    text = fake_async_wa.sent[-1].kwargs["text"]
    assert "you collected order" in text
    assert "31 min past the pickup time" in text
    assert "Please collect ASAP" not in text
    assert "head over now" not in text


async def test_notify_pickup_reminder_in_transit_never_claims_a_future_time_has_passed(
    fake_async_wa: FakeAsyncWhatsApp, patch_supabase_client
) -> None:
    """A negative offset in the delivery config must not produce a false statement."""
    await rider_agent.notify_pickup_reminder(
        {
            "rider_name": "Bas",
            "order_number": "ELAS-ABCD-1",
            "pickup_time": _pickup_time_in(9.2),
            "pickup_alert_offset": -10,
            "pickup_alert_phase": "picked_up",
        },
        "tool-1",
        _runtime(client=patch_supabase_client, wa=fake_async_wa),
    )

    text = fake_async_wa.sent[-1].kwargs["text"]
    assert "past the pickup time" not in text
    assert "still about 9 min away" in text


async def test_notify_pickup_reminder_clears_phase_with_offset(
    fake_async_wa: FakeAsyncWhatsApp, patch_supabase_client
) -> None:
    """A stale phase left in state would pick the wrong message next time."""
    result = await rider_agent.notify_pickup_reminder(
        {
            "rider_name": "Bas",
            "order_number": "ELAS-ABCD-1",
            "pickup_time": _pickup_time_in(-31.2),
            "pickup_alert_offset": 30,
            "pickup_alert_phase": "picked_up",
        },
        "tool-1",
        _runtime(client=patch_supabase_client, wa=fake_async_wa),
    )

    assert result.update["pickup_alert_offset"] is None
    assert result.update["pickup_alert_phase"] is None


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


def _dropoff_text(wa) -> str:
    return next(c.kwargs["text"] for c in reversed(wa.sent) if c.method == "send_message")


@pytest.mark.parametrize("precision, fragment", [("street", "street, not the door"), ("postcode", "postcode centre")])
async def test_dropoff_warns_rider_when_web_pin_is_approximate(patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp, precision, fragment) -> None:
    patch_supabase_client.register(table="delivery_summary", verb="select", response=FakeSupabaseResponse(data=[_summary_row()]))
    patch_supabase_client.register(table="web_order_request", verb="select", response=FakeSupabaseResponse(data=[{"address": {"pin_precision": precision}}]))

    await rider_agent.send_dropoff_location({"order_number": "ELAS-ABCD-1", "reply_to_msg_id": "msg-1"}, "tool-2", _runtime(client=patch_supabase_client, wa=fake_async_wa))

    text = _dropoff_text(fake_async_wa)
    assert text.startswith("Dropoff:\n") and "⚠️" in text and fragment in text


@pytest.mark.parametrize("data", [[], [{"address": None}], [{"address": {"pin_precision": "exact"}}], [{"address": {}}]])
async def test_dropoff_has_no_warning_for_exact_pin_or_whatsapp_order(patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp, data) -> None:
    patch_supabase_client.register(table="delivery_summary", verb="select", response=FakeSupabaseResponse(data=[_summary_row()]))
    patch_supabase_client.register(table="web_order_request", verb="select", response=FakeSupabaseResponse(data=data))

    await rider_agent.send_dropoff_location({"order_number": "ELAS-ABCD-1", "reply_to_msg_id": "msg-1"}, "tool-2", _runtime(client=patch_supabase_client, wa=fake_async_wa))

    assert "⚠️" not in _dropoff_text(fake_async_wa)


async def test_dropoff_survives_pin_lookup_failure(patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp) -> None:
    patch_supabase_client.register(table="delivery_summary", verb="select", response=FakeSupabaseResponse(data=[_summary_row()]))
    patch_supabase_client.register(table="web_order_request", verb="select", response=RuntimeError("db down"))

    result = await rider_agent.send_dropoff_location({"order_number": "ELAS-ABCD-1", "reply_to_msg_id": "msg-1"}, "tool-2", _runtime(client=patch_supabase_client, wa=fake_async_wa))

    assert result.update["messages"][0].content == "Dropoff location sent to user."
    assert "⚠️" not in _dropoff_text(fake_async_wa)


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


async def test_cancel_delivery_before_pickup_calls_rpc_and_sets_awaiting_reason(monkeypatch, patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp) -> None:
    async def verdict(_):
        return rider_agent.job_exit.Verdict.ASK_CONFIRM
    monkeypatch.setattr(rider_agent.job_exit, "verdict_for", verdict)
    patch_supabase_client.register_rpc("dispatch_cancel_before_pickup", FakeSupabaseResponse(data="cancelled dispatch 10 for order ELAS-ABCD-1"))

    result = await rider_agent.cancel_delivery_before_pickup(
        {"dispatch_id": 10, "order_number": "ELAS-ABCD-1", "rider_name": "Bas", "cancel_confirmed": True},
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
        def __init__(self, *, wa_client=None):
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
    closed = []

    async def fake_close(thread_id):
        closed.append(thread_id)
        return True

    monkeypatch.setattr(rider_agent.rider_threads, "close", fake_close)
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
    assert closed == ["ORDELO-dispatch-10"]  # exactly the run's own thread (R2), not every thread of the phone


async def test_request_rider_current_location_sends_intro_and_request_and_records_id(
    monkeypatch, patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp
) -> None:
    recorded = []

    class _FakeWaLocation:
        def __init__(self, *, wa_client=None):
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
        def __init__(self, *, wa_client=None):
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


async def test_verify_customer_confirmation_code_right_code_tells_the_restaurant_delivery_completed(
    monkeypatch, patch_pg_pool, patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp
) -> None:
    from utils_common.notify import restaurant_notifier
    from utils_common.notify.restaurant_notifier import DeliveryCompleted

    closed = []

    async def fake_close(thread_id):
        closed.append(thread_id)
        return True

    monkeypatch.setattr(rider_agent.rider_threads, "close", fake_close)
    patch_supabase_client.register(table="delivery_summary", verb="select", response=FakeSupabaseResponse(data=[_summary_row()]))
    patch_supabase_client.register_rpc("dispatch_complete_func", FakeSupabaseResponse(data=[{"ok": True}]))
    monkeypatch.setattr(rider_agent, "client_ordelo", patch_supabase_client)
    seen = []

    async def fake_notify(notice):
        seen.append(notice)

    async def no_customer_event(*a, **kw):
        return None

    monkeypatch.setattr(restaurant_notifier, "notify", fake_notify)
    monkeypatch.setattr(rider_agent, "post_rider_event_customer_cc", no_customer_event)

    result = await rider_agent.verify_customer_confirmation_code(
        22,
        {"dispatch_id": 10, "order_number": "ELAS-ABCD-1", "latest_wa_msg_id": "wa-msg"},
        "tool-1",
        _runtime(client=patch_supabase_client, wa=fake_async_wa),
    )

    assert result.update["is_customer_confirmation_code_verified"] is True
    assert seen == [DeliveryCompleted("ELAS-ABCD-1", "ELAS")]
    assert closed == ["ORDELO-dispatch-10"]


def test_cancel_confirmation_requires_trusted_tap():
    from ordelo.rider_messaging import cancel_tap_text
    text = cancel_tap_text("12345678", "yes")
    state = {"cancel_confirm_token": "12345678", "messages": [HumanMessage(text)]}
    result = rider_agent.agent_node(state)
    assert result.update["messages"][0].tool_calls[0]["name"] == "request_cancel_confirmation"
    state["messages"] = [HumanMessage(text, additional_kwargs={"cancel_tap": True})]
    result = rider_agent.agent_node(state)
    assert result.update["cancel_confirmed"] is True
    assert result.update["messages"][0].tool_calls[0]["name"] == "cancel_delivery_before_pickup"
    state["messages"] = [HumanMessage(cancel_tap_text("12345678", "no"), additional_kwargs={"cancel_tap": True})]
    result = rider_agent.agent_node(state)
    assert result.update["cancel_confirm_token"] is None
    assert "stays with you" in result.update["messages"][0].content
    state["messages"] = [HumanMessage(cancel_tap_text("87654321", "yes"), additional_kwargs={"cancel_tap": True})]
    assert "expired" in rider_agent.agent_node(state).update["messages"][0].content


async def test_unconfirmed_cancel_never_calls_rpc(monkeypatch, patch_supabase_client, fake_async_wa):
    async def verdict(_):
        return rider_agent.job_exit.Verdict.ASK_CONFIRM
    monkeypatch.setattr(rider_agent.job_exit, "verdict_for", verdict)
    result = await rider_agent.cancel_delivery_before_pickup(
        {"dispatch_id": 10, "order_number": "ORDER"}, "tool", _runtime(client=patch_supabase_client, wa=fake_async_wa))
    assert "Not confirmed" in result.update["messages"][0].content
    assert not patch_supabase_client.rpc_calls


async def test_terminate_assigned_sends_confirmation_without_closing(monkeypatch, patch_supabase_client, fake_async_wa):
    async def verdict(_):
        return rider_agent.job_exit.Verdict.ASK_CONFIRM
    monkeypatch.setattr(rider_agent.job_exit, "verdict_for", verdict)
    async def no_close(_):
        raise AssertionError("closed assigned job")
    monkeypatch.setattr(rider_agent, "_close_own_thread", no_close)
    result = await rider_agent.terminate_delivery_job({"dispatch_id": 10}, "tool", _runtime(client=patch_supabase_client, wa=fake_async_wa))
    assert result.update["cancel_confirm_token"]
    assert len(fake_async_wa.sent[-1].kwargs["buttons"]) == 2


async def test_terminate_picked_up_refuses_without_closing(monkeypatch, patch_supabase_client, fake_async_wa):
    async def verdict(_):
        return rider_agent.job_exit.Verdict.REFUSE
    async def refusal(state, ctx, words):
        await ctx.messenger.say("refused")
    async def no_close(_):
        raise AssertionError("closed picked-up job")
    monkeypatch.setattr(rider_agent.job_exit, "verdict_for", verdict)
    monkeypatch.setattr(rider_agent, "_exit_refusal", refusal)
    monkeypatch.setattr(rider_agent, "_close_own_thread", no_close)
    await rider_agent.terminate_delivery_job({"dispatch_id": 10}, "tool", _runtime(client=patch_supabase_client, wa=fake_async_wa))
    assert fake_async_wa.sent[-1].kwargs["text"] == "refused"


async def test_cancel_rpc_refusal_does_not_claim_success(monkeypatch, patch_supabase_client, fake_async_wa):
    responses = iter([rider_agent.job_exit.Verdict.ASK_CONFIRM, rider_agent.job_exit.Verdict.REFUSE])
    async def verdict(_):
        return next(responses)
    calls = []
    async def refusal(state, ctx, words):
        calls.append(words)
        await ctx.messenger.say("refused")
    monkeypatch.setattr(rider_agent.job_exit, "verdict_for", verdict)
    monkeypatch.setattr(rider_agent, "_exit_refusal", refusal)
    patch_supabase_client.register_rpc("dispatch_cancel_before_pickup", FakeSupabaseResponse(data="cannot cancel; dispatch status is pickedup"))
    result = await rider_agent.cancel_delivery_before_pickup(
        {"dispatch_id": 10, "order_number": "ORDER", "cancel_confirmed": True, "messages": [HumanMessage("cancel")]},
        "tool", _runtime(client=patch_supabase_client, wa=fake_async_wa))
    assert not result.update.get("awaiting_cancel_reason")
    assert result.update["cancel_confirmed"] is False
    assert "not completed" in result.update["messages"][0].content
    assert calls == ["cancel"]


async def test_terminate_unknown_status_keeps_thread_open(monkeypatch, patch_supabase_client, fake_async_wa):
    async def verdict(_):
        return rider_agent.job_exit.Verdict.UNKNOWN
    async def no_close(_):
        raise AssertionError("closed job after failed status read")
    monkeypatch.setattr(rider_agent.job_exit, "verdict_for", verdict)
    monkeypatch.setattr(rider_agent, "_close_own_thread", no_close)
    result = await rider_agent.terminate_delivery_job({"dispatch_id": 10}, "tool", _runtime(client=patch_supabase_client, wa=fake_async_wa))
    assert "not closed" in result.update["messages"][0].content
