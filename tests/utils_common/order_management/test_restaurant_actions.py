"""Tests for utils_common.order_management.restaurant_actions (Ready and adjust pickup, both channels).

The database is replaced by FakeActionsDb (tests/fixtures/fake_restaurant_actions.py), which mimics the RPC contract of
ordelo_datamodels/restaurant_admin/restaurant_ready_adjust_notices.sql. The SQL itself is verified in
tests/sql/test_restaurant_ready_adjust_notices_sql.py.

Key Functions:
  - test_ready_*          ready() RPC choice per actor, result mapping, and the follow-up that runs only on 'ok'
  - test_adjust_*         adjust_pickup() RPC choice per actor and result mapping
  - test_ready_reply_*    the WhatsApp wording for a Ready tap that did not run the follow-up
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ordelo.delivery_progress import GATE_REPLIES, DeliveryProgress
from utils_common.order_management import restaurant_actions as ra

ORDER = "ELAS-ABCD-1"
TAKE = "ELAS-WXYZ-9"
WA = ra.WhatsAppActor("447700900123")
TG = ra.TelegramActor("rest_admin", 111)


@pytest.fixture
def nudges(monkeypatch):
    """Records run_rider_agent_w_custom_msg calls (the rider follow-up)."""
    calls = []

    async def fake(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr("ordelo.agents.agent_runner.run_rider_agent_w_custom_msg", fake)
    return calls


@pytest.fixture
def events(monkeypatch):
    """Records customer_notifier.publish calls (the takeaway follow-up)."""
    calls = []

    async def fake(order_number, event):
        calls.append((order_number, event))

    monkeypatch.setattr(ra.customer_notifier, "publish", fake)
    return calls


# ---- ready: delivery --------------------------------------------------------------------------------------------


async def test_ready_whatsapp_calls_shared_rpc_and_nudges_rider_with_todays_text(actions_db, nudges):
    actions_db.add()
    out = await ra.ready(ORDER, "delivery", WA)
    assert out == ra.ActionOutcome(result="ok", by_label="…0123", by_phone="447700900123")
    assert actions_db.calls == [("restaurant_order_ready", {
        "p_order_number": ORDER, "p_order_type": "delivery", "p_admin_phone": "447700900123", "p_channel": "whatsapp"})]
    assert nudges == [{"recipient": "RIDER01",
                       "human_msg": "call `tool notify_food_ready_for_pickup`. Rider should hurry to Elai to pickup the food.",
                       "dispatch_id": 10}]  # that job's thread (R2), so the job's channel (D44)


async def test_ready_telegram_calls_wrapper_and_nudges_rider(actions_db, nudges):
    actions_db.add()
    actions_db.telegram_admins[("rest_admin", 111)] = "447700900555"
    actions_db.labels["447700900555"] = "Ada"
    out = await ra.ready(ORDER, "delivery", TG)
    assert out.result == "ok" and out.by_label == "Ada" and out.by_phone == "447700900555"
    assert actions_db.calls == [("t_order_ready", {
        "p_bot_key": "rest_admin", "p_tuid": 111, "p_order_number": ORDER, "p_order_type": "delivery"})]
    assert len(nudges) == 1 and nudges[0]["recipient"] == "RIDER01"


async def test_ready_second_tap_is_already_ready_with_label_and_no_second_nudge(actions_db, nudges):
    actions_db.add()
    actions_db.labels["447700900123"] = "Ada"
    await ra.ready(ORDER, "delivery", WA)
    out = await ra.ready(ORDER, "delivery", ra.WhatsAppActor("447700900999"))
    assert out.result == "already_ready" and out.by_label == "Ada" and out.by_phone == "447700900123"
    assert len(nudges) == 1


async def test_ready_whatsapp_then_telegram_race_only_one_nudge(actions_db, nudges):
    actions_db.add()
    actions_db.telegram_admins[("rest_admin", 111)] = "447700900555"
    first = await ra.ready(ORDER, "delivery", WA)
    second = await ra.ready(ORDER, "delivery", TG)
    assert (first.result, second.result) == ("ok", "already_ready")
    assert len(nudges) == 1


@pytest.mark.parametrize("dispatch_status,progress", [("pickedup", "picked_up"), ("completed", "picked_up")])
async def test_ready_after_pickup_has_no_follow_up(actions_db, nudges, dispatch_status, progress):
    actions_db.add(dispatch_status=dispatch_status)
    out = await ra.ready(ORDER, "delivery", WA)
    assert out.result == "not_ready_state" and out.progress == progress
    assert nudges == []


async def test_ready_with_no_rider_on_the_job_has_no_follow_up(actions_db, nudges):
    actions_db.add(rider=None)
    out = await ra.ready(ORDER, "delivery", WA)
    assert out.result == "not_ready_state" and out.progress == "not_in_progress"
    assert nudges == []


async def test_ready_unknown_order_and_unauthorised_telegram_user(actions_db, nudges):
    assert (await ra.ready("NOPE-1", "delivery", WA)).result == "not_found"
    actions_db.add()
    assert (await ra.ready(ORDER, "delivery", TG)).result == "not_authorised"  # tuid not linked to the restaurant
    assert nudges == []


async def test_ready_follow_up_failure_is_reported_not_raised(actions_db, monkeypatch):
    actions_db.add()

    async def boom(**kwargs):
        raise RuntimeError("rider agent down")

    monkeypatch.setattr("ordelo.agents.agent_runner.run_rider_agent_w_custom_msg", boom)
    out = await ra.ready(ORDER, "delivery", WA)
    assert out.result == "ok" and out.follow_up_failed is True
    # the Ready stays recorded: a retry is "already ready", not a second nudge
    assert (await ra.ready(ORDER, "delivery", WA)).result == "already_ready"


# ---- ready: takeaway ---------------------------------------------------------------------------------------------


async def test_ready_takeaway_publishes_exactly_todays_customer_event(actions_db, events):
    actions_db.add(TAKE, "takeaway", rider=None)
    out = await ra.ready(TAKE, "takeaway", WA)
    assert out.result == "ok"
    (order_number, event), = events
    assert order_number == TAKE
    assert (event.event_type, event.event_key, event.webhook_type, event.path_suffix) == (
        "ready_for_collection", "ready_for_collection", "order-takeaway-ready", "/WXYZ-9")
    p = event.payload
    assert (p["order_id"], p["order_number"], p["recipient"], p["admin_id"], p["event"]) == (
        "WXYZ-9", TAKE, "4474", "447700900123", "admin_takeaway_ready")
    assert datetime.fromisoformat(p["event_dtts"]).tzinfo is not None


async def test_ready_takeaway_telegram_records_the_resolved_admin_phone(actions_db, events):
    actions_db.add(TAKE, "takeaway", rider=None)
    actions_db.telegram_admins[("rest_admin", 111)] = "447700900555"
    await ra.ready(TAKE, "takeaway", TG)
    assert events[0][1].payload["admin_id"] == "447700900555"


async def test_ready_takeaway_twice_publishes_once_and_not_confirmed_publishes_none(actions_db, events):
    actions_db.add(TAKE, "takeaway", rider=None)
    await ra.ready(TAKE, "takeaway", WA)
    assert (await ra.ready(TAKE, "takeaway", WA)).result == "already_ready"
    assert len(events) == 1
    actions_db.add("ELAS-NEW-1", "takeaway", rider=None, status="restaurant_unconfirmed")
    assert (await ra.ready("ELAS-NEW-1", "takeaway", WA)).result == "not_ready_state"
    assert len(events) == 1


async def test_ready_takeaway_follow_up_failure_is_reported_not_raised(actions_db, monkeypatch):
    actions_db.add(TAKE, "takeaway", rider=None)

    async def boom(order_number, event):
        raise RuntimeError("outbox down")

    monkeypatch.setattr(ra.customer_notifier, "publish", boom)
    out = await ra.ready(TAKE, "takeaway", WA)
    assert out.result == "ok" and out.follow_up_failed is True


# ---- ready: bad input / bad RPC answers ----------------------------------------------------------------------------


async def test_ready_rejects_bad_order_type_before_calling_the_db(actions_db):
    with pytest.raises(ValueError):
        await ra.ready(ORDER, "pizza", WA)
    assert actions_db.calls == []


async def test_ready_rejects_unexpected_rpc_shapes(monkeypatch):
    class Bad:
        def __init__(self, data):
            self.data = data

        def rpc(self, name, args=None):
            return type("Q", (), {"execute": lambda s: type("R", (), {"data": self.data})()})()

    for data in (None, {"result": "surprise"}, {"result": "unchanged"}):  # 'unchanged' is an adjust result, not a Ready one
        monkeypatch.setattr(ra, "client_ordelo_service", Bad(data))
        with pytest.raises(RuntimeError):
            await ra.ready(ORDER, "delivery", WA)


async def test_ready_database_errors_propagate_to_the_caller(actions_db):
    actions_db.fail_with = RuntimeError("db down")
    with pytest.raises(RuntimeError):
        await ra.ready(ORDER, "delivery", WA)


# ---- adjust pickup -----------------------------------------------------------------------------------------------


async def test_adjust_whatsapp_sends_the_absolute_target_its_button_carries(actions_db):
    actions_db.add()
    out = await ra.adjust_pickup(ORDER, WA, target="2026-10-15T12:10:00+00:00")
    assert out == ra.ActionOutcome(result="ok", by_label="…0123", by_phone="447700900123", pickup_time="2026-10-15T12:10:00+00:00")
    assert actions_db.calls == [("restaurant_order_adjust_pickup", {
        "p_order_number": ORDER, "p_target": "2026-10-15T12:10:00+00:00",
        "p_admin_phone": "447700900123", "p_channel": "whatsapp"})]


async def test_adjust_whatsapp_accepts_aware_datetimes_only(actions_db):
    actions_db.add()
    out = await ra.adjust_pickup(ORDER, WA, target=datetime(2026, 10, 15, 12, 20, tzinfo=timezone.utc))
    assert out.result == "ok" and out.pickup_time == "2026-10-15T12:20:00+00:00"
    with pytest.raises(ValueError):
        await ra.adjust_pickup(ORDER, WA, target=datetime(2026, 10, 15, 12, 30))
    with pytest.raises(ValueError):
        await ra.adjust_pickup(ORDER, WA)  # no target


async def test_adjust_repeat_to_the_same_time_is_unchanged(actions_db):
    actions_db.add()
    await ra.adjust_pickup(ORDER, WA, target="2026-10-15T12:10:00+00:00")
    out = await ra.adjust_pickup(ORDER, WA, target="2026-10-15T12:10:00+00:00")
    assert out.result == "unchanged" and out.pickup_time == "2026-10-15T12:10:00+00:00"


async def test_adjust_telegram_minutes_are_relative_to_the_original_pickup(actions_db):
    actions_db.add()
    actions_db.telegram_admins[("rest_admin", 111)] = "447700900555"
    assert (await ra.adjust_pickup(ORDER, TG, minutes=20)).pickup_time == "2026-10-15T12:20:00+00:00"
    assert (await ra.adjust_pickup(ORDER, TG, minutes=10)).pickup_time == "2026-10-15T12:10:00+00:00"  # not 12:30
    assert (await ra.adjust_pickup(ORDER, TG, minutes=10)).result == "unchanged"
    assert actions_db.calls[0] == ("t_order_adjust_pickup", {
        "p_bot_key": "rest_admin", "p_tuid": 111, "p_order_number": ORDER, "p_minutes": 20})


@pytest.mark.parametrize("minutes", [None, 0, 15, 30])
async def test_adjust_telegram_rejects_other_minutes_before_calling_the_db(actions_db, minutes):
    with pytest.raises(ValueError):
        await ra.adjust_pickup(ORDER, TG, minutes=minutes)
    assert actions_db.calls == []


async def test_adjust_gate_states_and_authorisation(actions_db):
    actions_db.add(rider=None)
    out = await ra.adjust_pickup(ORDER, WA, target="2026-10-15T12:10:00+00:00")
    assert out.result == "not_ready_state" and out.progress == "not_in_progress"
    actions_db.add(dispatch_status="pickedup")
    assert (await ra.adjust_pickup(ORDER, WA, target="2026-10-15T12:10:00+00:00")).progress == "picked_up"
    assert (await ra.adjust_pickup("NOPE-1", WA, target="2026-10-15T12:10:00+00:00")).result == "not_found"
    actions_db.add()
    assert (await ra.adjust_pickup(ORDER, TG, minutes=10)).result == "not_authorised"


async def test_adjust_rejects_results_that_are_not_adjust_results(monkeypatch):
    class Odd:
        def rpc(self, name, args=None):
            return type("Q", (), {"execute": lambda s: type("R", (), {"data": {"result": "already_ready"}})()})()

    monkeypatch.setattr(ra, "client_ordelo_service", Odd())
    with pytest.raises(RuntimeError):
        await ra.adjust_pickup(ORDER, WA, target="2026-10-15T12:10:00+00:00")


# ---- wording ------------------------------------------------------------------------------------------------------


def test_ready_reply_text_keeps_todays_gate_strings_and_adds_already_ready():
    assert ra.ready_reply_text(ra.ActionOutcome("ok")) is None
    assert ra.ready_reply_text(ra.ActionOutcome("already_ready", by_label="Ada")) == "Already marked ready by Ada"
    assert ra.ready_reply_text(ra.ActionOutcome("already_ready")) == "Already marked ready"
    assert ra.ready_reply_text(ra.ActionOutcome("not_ready_state", progress="picked_up")) == "Invalid, food already pickedup"
    assert ra.ready_reply_text(ra.ActionOutcome("not_ready_state", progress="not_in_progress")) == GATE_REPLIES[DeliveryProgress.NOT_IN_PROGRESS]
    assert ra.ready_reply_text(ra.ActionOutcome("not_found")) == GATE_REPLIES[DeliveryProgress.NOT_IN_PROGRESS]  # as when no inflight row existed
    assert ra.ready_reply_text(ra.ActionOutcome("not_authorised")) == "Could not verify order status. Please retry."
    assert ra.ready_reply_text(ra.ActionOutcome("ok", follow_up_failed=True)).startswith("Marked ready, but")
    assert ra.not_done_reply_text(ra.ActionOutcome("not_ready_state", progress="picked_up")) == "Invalid, food already pickedup"
