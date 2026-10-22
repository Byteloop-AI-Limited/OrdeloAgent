"""Tests for WhatsApp callback button handlers.

Callback handlers are exercised with fake pywa messages and patched side-effect
functions to cover dispatch gating, shift/admin availability, restaurant order
confirmation, pickup-time updates, and ready notifications.

Key Functions:
  - test_dispatch_response_handles_missing_and_inflight_orders
  - test_dispatch_response_accept_marks_the_offer_accepted_without_a_message
  - test_dispatch_response_sends_the_unchanged_whatsapp_texts
  - test_rider_request_location_handles_completed_missing_and_active_dispatch
  - test_handle_shift_availability_yes_no_and_on_job_paths (rule faked: ordelo.rider_shift)
  - test_handle_shift_availability_yes_from_a_rider_who_is_not_active
  - test_handle_shift_availability_unknown_number_gets_the_old_reply
  - test_handle_admin_availability_replies
  - test_update_restaurant_order_status_success_and_stale_tap
  - test_update_restaurant_order_status_decline_and_stale_tap_names_the_decliner
  - test_update_restaurant_order_status_after_timeout_says_auto_accepted
  - test_update_restaurant_order_status_unknown_order_or_status_does_not_reply
  - test_update_restaurant_order_status_swallows_database_errors
  - test_restaurant_order_accept_decline_schedules_update
  - test_handle_pickup_time_selection_success_and_already_updated
  - test_handle_pickup_time_selection_takeaway_and_not_accepted
  - test_handle_pickup_time_selection_swallows_database_errors
  - test_admin_collection_ready_runs_rider_graph
  - test_admin_collection_ready_skips_once_food_is_picked_up
  - test_admin_collection_ready_skips_when_no_longer_in_progress
  - test_admin_takeaway_ready_validates_and_posts_webhook
  - test_admin_adjust_pickup_time_updates_summary
  - test_admin_adjust_pickup_time_missing_data
  - test_admin_adjust_pickup_time_skips_when_picked_up
  - test_admin_adjust_pickup_time_skips_when_not_in_progress
  - test_admin_adjust_pickup_time_skips_when_progress_unknown
  - test_admin_adjust_pickup_time_unchanged_does_not_write
  - test_admin_adjust_pickup_time_database_error_asks_to_retry
  - test_admin_collection_ready_second_tap_replies_already_ready_no_nudge
  - test_admin_collection_ready_legacy_button_without_order_number
  - test_admin_collection_ready_follow_up_failure_tells_the_admin
  - test_admin_takeaway_ready_second_tap_replies_already_ready
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
import respx

from watomation import on_callback_wa_handler as handler
from ordelo.delivery_progress import GATE_REPLIES, DeliveryProgress
from tests.fixtures.fake_supabase import FakeSupabaseResponse
from tests.fixtures.fake_wa import FakeAsyncWhatsApp, FakeMessage


class _FakeCallback:
    def __init__(self, *, data: str, sender: str = "ADMIN01") -> None:
        self.data = data
        self.sender = sender
        self.replies = []

    async def reply(self, text: str):
        self.replies.append(text)


def _progress(state: DeliveryProgress, row: dict | None = None):
    async def _check(**_kwargs):
        return state, row

    return _check


def _dispatch_payload(**overrides) -> str:
    payload = {"command": "/dispatchResponse", "order_number": "ELAS-ABCD-1", "dispatch_id": 10, "status": "accepted"}
    payload.update(overrides)
    return json.dumps(payload)


async def test_dispatch_response_handles_missing_and_inflight_orders(patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp) -> None:
    patch_supabase_client.register(table="delivery_summary", verb="select", response=FakeSupabaseResponse(data=[]))
    await handler.dispatch_response(fake_async_wa, FakeMessage(sender="RIDER01", data=_dispatch_payload()))
    assert fake_async_wa.sent[-1].kwargs["text"] == "Sorry, This job is no longer available"

    patch_supabase_client.register(table="delivery_summary", verb="select", response=FakeSupabaseResponse(data=[{"status": "assigned"}]))
    patch_supabase_client.register(table="delivery_inflight", verb="select", response=FakeSupabaseResponse(data=[{"rider_id": "RIDER01", "dispatch_id": 10, "order_number": "ELAS-ABCD-1"}]))
    await handler.dispatch_response(fake_async_wa, FakeMessage(sender="RIDER01", data=_dispatch_payload(status="accepted")))
    assert fake_async_wa.sent[-1].kwargs["text"] == "Sorry, You are already on a job ELAS-ABCD-1"

    patch_supabase_client.register(table="delivery_inflight", verb="select", response=FakeSupabaseResponse(data=[{"rider_id": "OTHER", "dispatch_id": 10, "order_number": "ELAS-ABCD-1"}]))
    await handler.dispatch_response(fake_async_wa, FakeMessage(sender="RIDER01", data=_dispatch_payload()))
    assert fake_async_wa.sent[-1].kwargs["text"] == "Sorry, this job was picked up by another rider."


async def test_dispatch_response_accept_marks_the_offer_accepted_without_a_message(patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp) -> None:
    """Since R4 the rules run in ordelo.dispatch_actions.respond_to_offer (shared with Telegram, D48)."""
    patch_supabase_client.register(table="delivery_summary", verb="select", response=FakeSupabaseResponse(data=[{"status": "unassigned"}]))
    patch_supabase_client.register(table="delivery_inflight", verb="select", response=FakeSupabaseResponse(data=[]))

    await handler.dispatch_response(fake_async_wa, FakeMessage(sender="RIDER01", data=_dispatch_payload()))

    assert fake_async_wa.sent == []
    assert patch_supabase_client.calls[-1].payload == {"status": "accepted"}


async def test_dispatch_response_sends_the_unchanged_whatsapp_texts(patch_supabase_client, fake_async_wa: FakeAsyncWhatsApp) -> None:
    patch_supabase_client.register(table="delivery_summary", verb="select", response=FakeSupabaseResponse(data=[]))
    await handler.dispatch_response(fake_async_wa, FakeMessage(sender="RIDER01", data=_dispatch_payload()))
    assert fake_async_wa.sent[-1].kwargs == {"to": "RIDER01", "text": "Sorry, This job is no longer available"}

    patch_supabase_client.register(table="delivery_summary", verb="select", response=FakeSupabaseResponse(data=[{"status": "inflight"}]))
    patch_supabase_client.register(table="delivery_inflight", verb="select",
                                   response=FakeSupabaseResponse(data=[{"rider_id": "OTHER", "dispatch_id": 11, "order_number": "ELAS-ABCD-1"}]))
    await handler.dispatch_response(fake_async_wa, FakeMessage(sender="RIDER01", data=_dispatch_payload()))
    assert fake_async_wa.sent[-1].kwargs == {"to": "RIDER01", "text": "Sorry, this job was picked up by another rider."}

    patch_supabase_client.register(table="delivery_inflight", verb="select",
                                   response=FakeSupabaseResponse(data=[{"rider_id": "RIDER01", "dispatch_id": 9, "order_number": "ELAS-ABCD-1"}]))
    await handler.dispatch_response(fake_async_wa, FakeMessage(sender="RIDER01", data=_dispatch_payload()))
    assert fake_async_wa.sent[-1].kwargs == {"to": "RIDER01", "text": "Sorry, You are already on a job ELAS-ABCD-1"}


async def test_rider_request_location_handles_completed_missing_and_active_dispatch(monkeypatch, fake_async_wa: FakeAsyncWhatsApp) -> None:
    monkeypatch.setattr(handler.DeliveryDispatch, "from_dispatch_id", classmethod(lambda cls, dispatch_id: (_ for _ in ()).throw(ValueError("missing"))))
    await handler.rider_request_location(fake_async_wa, FakeMessage(data=json.dumps({"dispatch_id": 1, "recipient": "RIDER01", "human_msg": "pickup"})))
    assert fake_async_wa.sent == []

    monkeypatch.setattr(handler.DeliveryDispatch, "from_dispatch_id", classmethod(lambda cls, dispatch_id: SimpleNamespace(status="completed")))
    await handler.rider_request_location(fake_async_wa, FakeMessage(data=json.dumps({"dispatch_id": 1, "recipient": "RIDER01", "human_msg": "pickup"})))
    assert fake_async_wa.sent[-1].kwargs["text"] == "This job is expired."

    calls = []

    async def _fake_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(handler.DeliveryDispatch, "from_dispatch_id", classmethod(lambda cls, dispatch_id: SimpleNamespace(status="assigned")))
    monkeypatch.setattr(handler, "run_rider_agent_w_custom_msg", _fake_run)
    await handler.rider_request_location(fake_async_wa, FakeMessage(data=json.dumps({"dispatch_id": 1, "recipient": "RIDER01", "human_msg": "pickup"})))
    assert calls == [{"recipient": "RIDER01", "human_msg": "pickup", "dispatch_id": 1}]  # that dispatch's thread (R2)


@pytest.fixture
def shift_rule(monkeypatch):
    """Fakes ordelo.rider_shift.set_shift (the rider_set_shift RPC, proven in tests/sql/test_rider_shift_sql.py)."""
    from ordelo import rider_shift

    class Rule:
        outcome = rider_shift.ShiftOutcome(rider_shift.ON)
        calls: list[tuple[str, bool]] = []

    rule = Rule()
    rule.calls = []

    async def fake_set_shift(rider_id, on):
        rule.calls.append((rider_id, on))
        return rule.outcome

    monkeypatch.setattr(handler.rider_shift, "set_shift", fake_set_shift)
    return rule


async def test_handle_shift_availability_yes_no_and_on_job_paths(shift_rule, fake_async_wa: FakeAsyncWhatsApp) -> None:
    """The WhatsApp texts are the ones riders always got; the rule decides (R5)."""
    from ordelo import rider_shift

    yes = json.dumps({"recipient": "RIDER01", "human_msg": "Yes"})
    no = json.dumps({"recipient": "RIDER01", "human_msg": "No"})
    await handler.handle_shift_availability(fake_async_wa, FakeMessage(data=yes))
    assert fake_async_wa.sent[-1].kwargs == {"to": "RIDER01", "text": "Great! You will receive notifications for new jobs."}

    shift_rule.outcome = rider_shift.ShiftOutcome(rider_shift.ON_JOB, order_number="ELAS-ABCD-1")
    await handler.handle_shift_availability(fake_async_wa, FakeMessage(data=no))
    assert fake_async_wa.sent[-1].kwargs["text"] == ("You are currently on a job for order ELAS-ABCD-1. "
                                                     "Please complete the job first.")

    shift_rule.outcome = rider_shift.ShiftOutcome(rider_shift.OFF)
    await handler.handle_shift_availability(fake_async_wa, FakeMessage(data=no))
    assert fake_async_wa.sent[-1].kwargs["text"] == "Ok. You will not receive job notifications for the next 24 hrs."
    assert shift_rule.calls == [("RIDER01", True), ("RIDER01", False), ("RIDER01", False)]


async def test_handle_shift_availability_yes_from_a_rider_who_is_not_active(shift_rule, fake_async_wa: FakeAsyncWhatsApp) -> None:
    from ordelo import rider_shift

    shift_rule.outcome = rider_shift.ShiftOutcome(rider_shift.NOT_ACTIVE, status="inactive")
    await handler.handle_shift_availability(fake_async_wa, FakeMessage(data=json.dumps({"recipient": "RIDER01", "human_msg": "Yes"})))
    assert fake_async_wa.sent[-1].kwargs["text"] == handler.SHIFT_NOT_ACTIVE_TEXT
    assert "not active" in handler.SHIFT_NOT_ACTIVE_TEXT


@pytest.mark.parametrize("answer, text", [("Yes", "Great! You will receive notifications for new jobs."),
                                          ("No", "Ok. You will not receive job notifications for the next 24 hrs.")])
async def test_handle_shift_availability_unknown_number_gets_the_old_reply(shift_rule, fake_async_wa, answer, text) -> None:
    from ordelo import rider_shift

    shift_rule.outcome = rider_shift.ShiftOutcome(rider_shift.NOT_FOUND)
    await handler.handle_shift_availability(fake_async_wa, FakeMessage(data=json.dumps({"recipient": "RIDER09", "human_msg": answer})))
    assert fake_async_wa.sent[-1].kwargs["text"] == text


async def test_handle_admin_availability_replies() -> None:
    msg = FakeMessage(data=json.dumps({"recipient": "ADMIN01"}))

    await handler.handle_admin_availability(FakeAsyncWhatsApp(), msg)

    assert msg.replies == [{"text": "Great! You will receive notification for new orders for the next 24 hrs!"}]


ORDER = "ELAS-ABCD-1"
ADMIN = "447700900123"
OTHER_ADMIN = "447700900999"


async def test_update_restaurant_order_status_success_and_stale_tap(decision_db) -> None:
    decision_db.add(ORDER)
    msg = FakeMessage(sender=ADMIN)

    await handler._update_restaurant_order_status(ORDER, "restaurant_accept", msg)

    assert decision_db.calls[-1] == ("restaurant_order_decide", {
        "p_order_number": ORDER, "p_order_type": "delivery", "p_decision": "accept",
        "p_admin_phone": ADMIN, "p_channel": "whatsapp"})
    assert msg.replies == []

    late = FakeMessage(sender=OTHER_ADMIN)
    await handler._update_restaurant_order_status(ORDER, "restaurant_accept", late)
    assert late.replies[-1] == {"text": "Order already accepted by …0123"}


async def test_update_restaurant_order_status_decline_and_stale_tap_names_the_decliner(decision_db) -> None:
    decision_db.add(ORDER, kind="takeaway")
    msg = FakeMessage(sender=ADMIN)

    await handler._update_restaurant_order_status(ORDER, "restaurant_decline", msg, order_type="takeaway")

    assert decision_db.calls[-1][1]["p_decision"] == "decline"
    assert decision_db.calls[-1][1]["p_order_type"] == "takeaway"
    assert decision_db.orders[("takeaway", ORDER)]["rcs"] == "restaurant_decline"
    late = FakeMessage(sender=OTHER_ADMIN)
    await handler._update_restaurant_order_status(ORDER, "restaurant_accept", late, order_type="takeaway")
    assert late.replies[-1] == {"text": "Order already declined by …0123"}


async def test_update_restaurant_order_status_after_timeout_says_auto_accepted(decision_db) -> None:
    decision_db.add(ORDER, rcs="auto_accept")
    msg = FakeMessage(sender=ADMIN)

    await handler._update_restaurant_order_status(ORDER, "restaurant_accept", msg)

    assert msg.replies[-1] == {"text": "Order already auto-accepted (no answer in time)"}


async def test_update_restaurant_order_status_unknown_order_or_status_does_not_reply(decision_db) -> None:
    msg = FakeMessage(sender=ADMIN)

    await handler._update_restaurant_order_status("NOPE-1", "restaurant_accept", msg)
    await handler._update_restaurant_order_status(ORDER, "restaurant_unconfirmed", msg)

    assert msg.replies == []
    assert [c[1]["p_order_number"] for c in decision_db.calls] == ["NOPE-1"]   # a bad status never reaches the database


async def test_update_restaurant_order_status_swallows_database_errors(monkeypatch) -> None:
    async def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(handler.restaurant_decision, "decide", boom)
    msg = FakeMessage(sender=ADMIN)

    await handler._update_restaurant_order_status(ORDER, "restaurant_accept", msg)   # must not raise

    assert msg.replies == []


async def test_restaurant_order_accept_decline_schedules_update(monkeypatch, fake_async_wa: FakeAsyncWhatsApp) -> None:
    scheduled = []

    def _fake_create_task(coro):
        scheduled.append(coro)
        coro.close()
        return SimpleNamespace(cancel=lambda: None)

    async def _fake_update(*args, **kwargs):
        return None

    monkeypatch.setattr(handler.asyncio, "create_task", _fake_create_task)
    monkeypatch.setattr(handler, "_update_restaurant_order_status", _fake_update)
    data = json.dumps({"action": "/RestaurantOrder-Accept", "order_number": "ELAS-ABCD-1", "order_time": 123, "order_type": "delivery"})

    await handler.restaurant_order_accept_decline_handler(fake_async_wa, FakeMessage(sender="ADMIN01", data=data))

    assert len(scheduled) == 1


async def test_handle_pickup_time_selection_success_and_already_updated(decision_db) -> None:
    pickup = "2026-10-15T12:15:00+01:00"
    data = json.dumps({"action": "/PickupTime", "order_number": ORDER, "pickup_time": pickup, "order_type": "delivery"})
    decision_db.add(ORDER, rcs="restaurant_accept")
    msg = FakeMessage(sender=ADMIN, data=data)

    await handler.handle_pickup_time_selection(FakeAsyncWhatsApp(), msg)
    assert msg.replies[-1] == {"text": "Pickup time updated"}
    assert decision_db.calls[-1] == ("restaurant_order_set_pickup", {
        "p_order_number": ORDER, "p_order_type": "delivery", "p_pickup_time": pickup,
        "p_admin_phone": ADMIN, "p_channel": "whatsapp"})

    await handler.handle_pickup_time_selection(FakeAsyncWhatsApp(), msg)
    assert msg.replies[-1] == {"text": "Pickup time already updated"}


async def test_handle_pickup_time_selection_takeaway_and_not_accepted(decision_db) -> None:
    data = json.dumps({"action": "/PickupTime", "order_number": ORDER, "pickup_time": "2026-10-15T12:15:00+01:00", "order_type": "takeaway"})
    decision_db.add(ORDER, kind="takeaway", rcs="auto_accept")   # timed out before the admin chose
    msg = FakeMessage(sender=ADMIN, data=data)

    await handler.handle_pickup_time_selection(FakeAsyncWhatsApp(), msg)

    assert decision_db.calls[-1][1]["p_order_type"] == "takeaway"
    assert msg.replies[-1] == {"text": "Pickup time already updated"}


async def test_handle_pickup_time_selection_swallows_database_errors(monkeypatch) -> None:
    async def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(handler.restaurant_decision, "set_pickup", boom)
    data = json.dumps({"action": "/PickupTime", "order_number": ORDER, "pickup_time": "2026-10-15T12:15:00+01:00"})
    msg = FakeMessage(sender=ADMIN, data=data)

    await handler.handle_pickup_time_selection(FakeAsyncWhatsApp(), msg)   # must not raise

    assert msg.replies == []


def _adjust_callback(**overrides) -> _FakeCallback:
    payload = {
        "action": "/AdminAdjustPickupTime10",
        "order_number": "ELAS-ABCD-1",
        "pickup_time": "2026-05-09T11:40:00+00:00",
    }
    payload.update(overrides)
    return _FakeCallback(data=json.dumps(payload), sender="ADMIN01")


async def test_admin_adjust_pickup_time_updates_summary(actions_db) -> None:
    actions_db.add("ELAS-ABCD-1", pickup="2026-05-09T11:30:00+00:00")
    callback = _adjust_callback()

    await handler.admin_adjust_pickup_time(FakeAsyncWhatsApp(), callback)

    assert actions_db.calls == [("restaurant_order_adjust_pickup", {
        "p_order_number": "ELAS-ABCD-1", "p_target": "2026-05-09T11:40:00+00:00",
        "p_admin_phone": "ADMIN01", "p_channel": "whatsapp"})]
    assert actions_db.orders[("delivery", "ELAS-ABCD-1")]["pickup"] == "2026-05-09T11:40:00+00:00"
    assert callback.replies  # admin received a confirmation
    assert callback.replies[-1].startswith("Pickup time updated to ")


async def test_admin_adjust_pickup_time_unchanged_does_not_write(actions_db) -> None:
    actions_db.add("ELAS-ABCD-1", pickup="2026-05-09T11:40:00+00:00")   # already at the tapped time
    callback = _adjust_callback()

    await handler.admin_adjust_pickup_time(FakeAsyncWhatsApp(), callback)

    order = actions_db.orders[("delivery", "ELAS-ABCD-1")]
    assert order["initial"] is None and order["adjusted_by"] is None     # nothing was written (so no trigger, no rider message)
    assert callback.replies[-1].startswith("Pickup time updated to ")    # the admin sees the state they asked for


async def test_admin_adjust_pickup_time_missing_data(actions_db) -> None:
    callback = _FakeCallback(data=json.dumps({"action": "/AdminAdjustPickupTime10"}))

    await handler.admin_adjust_pickup_time(FakeAsyncWhatsApp(), callback)

    assert callback.replies[-1] == "Missing order or pickup time in callback. Please retry."
    assert actions_db.calls == []


async def test_admin_adjust_pickup_time_skips_when_picked_up(actions_db) -> None:
    actions_db.add("ELAS-ABCD-1", dispatch_status="pickedup")
    callback = _adjust_callback()

    await handler.admin_adjust_pickup_time(FakeAsyncWhatsApp(), callback)

    assert actions_db.orders[("delivery", "ELAS-ABCD-1")]["adjusted_by"] is None
    assert callback.replies[-1] == GATE_REPLIES[DeliveryProgress.PICKED_UP]
    assert callback.replies[-1] == "Invalid, food already pickedup"


async def test_admin_adjust_pickup_time_skips_when_not_in_progress(actions_db) -> None:
    actions_db.add("ELAS-ABCD-1", rider=None)
    callback = _adjust_callback()

    await handler.admin_adjust_pickup_time(FakeAsyncWhatsApp(), callback)

    assert actions_db.orders[("delivery", "ELAS-ABCD-1")]["adjusted_by"] is None
    assert callback.replies[-1] == GATE_REPLIES[DeliveryProgress.NOT_IN_PROGRESS]


async def test_admin_adjust_pickup_time_skips_when_progress_unknown(actions_db) -> None:
    """The order is not found at all: the same words as 'no longer in progress' (as when no inflight row existed)."""
    callback = _adjust_callback()

    await handler.admin_adjust_pickup_time(FakeAsyncWhatsApp(), callback)

    assert callback.replies[-1] == GATE_REPLIES[DeliveryProgress.NOT_IN_PROGRESS]


async def test_admin_adjust_pickup_time_database_error_asks_to_retry(actions_db) -> None:
    actions_db.fail_with = RuntimeError("db down")
    callback = _adjust_callback()

    await handler.admin_adjust_pickup_time(FakeAsyncWhatsApp(), callback)

    assert callback.replies[-1] == "Failed to update pickup time. Please retry."


def _collection_ready_callback(**overrides) -> _FakeCallback:
    payload = {
        "action": "/AdminCollectionReady",
        "rider_id": "RIDER01",
        "restaurant_name": "Elai",
        "order_number": "ELAS-ABCD-1",
    }
    payload.update(overrides)
    return _FakeCallback(data=json.dumps(payload))


@pytest.fixture
def rider_nudges(monkeypatch):
    calls = []

    async def _fake_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr("ordelo.agents.agent_runner.run_rider_agent_w_custom_msg", _fake_run)
    return calls


async def test_admin_collection_ready_runs_rider_graph(actions_db, rider_nudges) -> None:
    actions_db.add("ELAS-ABCD-1", rider="RIDER01", rest_name="Elai")
    callback = _collection_ready_callback()

    await handler.admin_collection_ready(FakeAsyncWhatsApp(), callback)

    assert rider_nudges[0]["recipient"] == "RIDER01"
    assert "notify_food_ready_for_pickup" in rider_nudges[0]["human_msg"]
    assert "Rider should hurry to Elai to pickup the food." in rider_nudges[0]["human_msg"]
    assert callback.replies == []   # today: no reply on success


async def test_admin_collection_ready_second_tap_replies_already_ready_no_nudge(actions_db, rider_nudges) -> None:
    actions_db.add("ELAS-ABCD-1")
    actions_db.labels["ADMIN01"] = "Ada"
    first, second = _collection_ready_callback(), _FakeCallback(data=_collection_ready_callback().data, sender="ADMIN02")

    await handler.admin_collection_ready(FakeAsyncWhatsApp(), first)
    await handler.admin_collection_ready(FakeAsyncWhatsApp(), second)

    assert len(rider_nudges) == 1
    assert second.replies == ["Already marked ready by Ada"]


async def test_admin_collection_ready_skips_once_food_is_picked_up(actions_db, rider_nudges) -> None:
    actions_db.add("ELAS-ABCD-1", dispatch_status="pickedup")
    callback = _collection_ready_callback()

    await handler.admin_collection_ready(FakeAsyncWhatsApp(), callback)

    assert rider_nudges == []
    assert callback.replies[-1] == GATE_REPLIES[DeliveryProgress.PICKED_UP]
    assert callback.replies[-1] == "Invalid, food already pickedup"


async def test_admin_collection_ready_skips_when_no_longer_in_progress(actions_db, rider_nudges) -> None:
    actions_db.add("ELAS-ABCD-1", rider=None)
    callback = _collection_ready_callback()

    await handler.admin_collection_ready(FakeAsyncWhatsApp(), callback)

    assert rider_nudges == []
    assert callback.replies[-1] == GATE_REPLIES[DeliveryProgress.NOT_IN_PROGRESS]


async def test_admin_collection_ready_database_error_fails_closed(actions_db, rider_nudges) -> None:
    actions_db.fail_with = RuntimeError("db down")
    callback = _collection_ready_callback()

    await handler.admin_collection_ready(FakeAsyncWhatsApp(), callback)

    assert rider_nudges == []
    assert callback.replies[-1] == GATE_REPLIES[DeliveryProgress.UNKNOWN]


async def test_admin_collection_ready_follow_up_failure_tells_the_admin(actions_db, monkeypatch) -> None:
    actions_db.add("ELAS-ABCD-1")

    async def _boom(**kwargs):
        raise RuntimeError("rider agent down")

    monkeypatch.setattr("ordelo.agents.agent_runner.run_rider_agent_w_custom_msg", _boom)
    callback = _collection_ready_callback()

    await handler.admin_collection_ready(FakeAsyncWhatsApp(), callback)

    assert callback.replies == ["Marked ready, but the message to the rider could not be sent. Please call the rider."]


async def test_admin_collection_ready_legacy_button_without_order_number(monkeypatch) -> None:
    """Buttons sent before order_number existed keep the old rider_id gate and the old nudge."""
    calls = []

    async def _fake_run(**kwargs):
        calls.append(kwargs)

    async def _check(**kwargs):
        assert kwargs == {"rider_id": "RIDER01", "order_number": None}
        return DeliveryProgress.AWAITING_PICKUP, {}

    monkeypatch.setattr(handler, "run_rider_agent_w_custom_msg", _fake_run)
    monkeypatch.setattr(handler, "check_delivery_progress", _check)
    callback = _FakeCallback(data=json.dumps({"action": "/AdminCollectionReady", "rider_id": "RIDER01", "restaurant_name": "Elai"}))

    await handler.admin_collection_ready(FakeAsyncWhatsApp(), callback)

    assert calls[0]["recipient"] == "RIDER01" and "Elai" in calls[0]["human_msg"]


@respx.mock
async def test_admin_takeaway_ready_validates_and_posts_webhook(monkeypatch, inline_notifier, actions_db) -> None:
    invalid = _FakeCallback(data=json.dumps({"action": "/AdminTakeawayReady", "order_number": "BAD"}))
    await handler.admin_takeaway_ready(FakeAsyncWhatsApp(), invalid)
    assert invalid.replies == ["Missing order number in callback. Please retry."]
    assert actions_db.calls == []

    async def _webhook(rest_ref, webhook_type):
        return "https://rest.example.com/takeaway-ready"

    inline_notifier.webhook = _webhook
    inline_notifier.recipient = "4474"
    actions_db.add("ELAS-ABCD-1", "takeaway", rider=None, recipient="4474")
    route = respx.post("https://rest.example.com/takeaway-ready/ABCD-1").mock(return_value=httpx.Response(200, json={"ok": True}))
    callback = _FakeCallback(data=json.dumps({"action": "/AdminTakeawayReady", "order_number": "ELAS-ABCD-1", "recipient": "4474"}), sender="ADMIN01")

    await handler.admin_takeaway_ready(FakeAsyncWhatsApp(), callback)

    assert route.called
    assert callback.replies[-1] == "Customer notification request sent."


async def test_admin_takeaway_ready_second_tap_replies_already_ready(actions_db, monkeypatch) -> None:
    published = []

    async def _publish(order_number, event):
        published.append(order_number)

    monkeypatch.setattr(handler.restaurant_actions.customer_notifier, "publish", _publish)
    actions_db.add("ELAS-ABCD-1", "takeaway", rider=None)
    actions_db.labels["ADMIN01"] = "Ada"
    data = json.dumps({"action": "/AdminTakeawayReady", "order_number": "ELAS-ABCD-1", "recipient": "4474"})
    first, second = _FakeCallback(data=data, sender="ADMIN01"), _FakeCallback(data=data, sender="ADMIN02")

    await handler.admin_takeaway_ready(FakeAsyncWhatsApp(), first)
    await handler.admin_takeaway_ready(FakeAsyncWhatsApp(), second)

    assert first.replies == ["Customer notification request sent."]
    assert second.replies == ["Already marked ready by Ada"]
    assert published == ["ELAS-ABCD-1"]   # the customer is told once
