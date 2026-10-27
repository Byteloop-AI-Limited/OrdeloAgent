"""ordelo.dispatch_actions: a rider's Accept / Decline on any channel (D48) and closing Telegram offers (D49).

Every OfferOutcome, the unchanged WhatsApp texts, the database writes each outcome makes, and close_open_offers editing only
still-open Telegram offers (the winner as 'assigned'). REST is faked (FakeSupabaseClient); messengers are recorded.
"""

from __future__ import annotations

import pytest

from ordelo import dispatch_actions as da
from ordelo.rider_messaging import use_messenger
from ordelo.rider_messaging.fake import RecordingRiderMessenger
from tests.fixtures.fake_supabase import FakeSupabaseResponse

ORDER = "ELAS-ABCD-1"
R = "447700900601"


def _db(fake, *, summary=({"status": "unassigned"},), inflight=(), assigned_rows=()):
    fake.register(table="delivery_summary", verb="select", response=FakeSupabaseResponse(data=list(summary)))
    fake.register(table="delivery_inflight", verb="select", response=FakeSupabaseResponse(data=list(inflight)))

    def update(call):  # the decline probe filters on status = 'assigned'
        if call.filters.get("eq:status") == "assigned":
            return FakeSupabaseResponse(data=list(assigned_rows))
        return FakeSupabaseResponse(data=[{"dispatch_id": 10}])

    fake.register(table="delivery_dispatch", verb="update", response=update)


def _updates(fake):
    return [(c.payload, c.filters) for c in fake.calls if c.table == "delivery_dispatch" and c.verb == "update"]


@pytest.fixture
def agent_runs(monkeypatch):
    runs = []

    async def fake_run(**kwargs):
        runs.append(kwargs)

    monkeypatch.setattr("ordelo.agents.agent_runner.run_rider_agent_w_custom_msg", fake_run)
    return runs


async def test_no_summary_row_is_gone(patch_supabase_client, agent_runs):
    _db(patch_supabase_client, summary=())
    out = await da.respond_to_offer(R, 10, ORDER, True)
    assert out == da.OfferOutcome(da.GONE, ORDER, 10)
    assert da.whatsapp_reply(out) == "Sorry, This job is no longer available"
    assert _updates(patch_supabase_client) == []


async def test_order_inflight_with_another_rider_is_taken(patch_supabase_client, agent_runs):
    _db(patch_supabase_client, summary=({"status": "inflight"},), inflight=({"rider_id": "OTHER", "dispatch_id": 11, "order_number": ORDER},))
    out = await da.respond_to_offer(R, 10, ORDER, True)
    assert out.result == da.TAKEN and da.whatsapp_reply(out) == "Sorry, this job was picked up by another rider."


@pytest.mark.parametrize("accept, dispatch_id", [(True, 10), (False, 9)])
async def test_already_on_this_job(patch_supabase_client, agent_runs, accept, dispatch_id):
    """Any tap except a decline of the rider's own live dispatch."""
    _db(patch_supabase_client, summary=({"status": "inflight"},), inflight=({"rider_id": R, "dispatch_id": 10, "order_number": ORDER},))
    out = await da.respond_to_offer(R, dispatch_id, ORDER, accept)
    assert out == da.OfferOutcome(da.ALREADY_ON_THIS_JOB, ORDER, dispatch_id, ORDER)
    assert da.whatsapp_reply(out) == f"Sorry, You are already on a job {ORDER}"
    assert agent_runs == [] and _updates(patch_supabase_client) == []


async def test_declining_your_own_assigned_job_runs_the_cancel_flow(patch_supabase_client, agent_runs):
    _db(patch_supabase_client, summary=({"status": "inflight"},), inflight=({"rider_id": R, "dispatch_id": 10, "order_number": ORDER},),
        assigned_rows=({"dispatch_id": 10},))
    out = await da.respond_to_offer(R, 10, ORDER, False)
    assert out.result == da.CANCEL_OWN_JOB and da.whatsapp_reply(out) is None
    assert agent_runs == [{"recipient": R, "dispatch_id": 10, "system_msg": "call `tool request_cancel_confirmation` with the rider request",
                           "human_msg": f"I need to cancel order {ORDER} before pickup."}]


async def test_declining_an_open_offer_marks_it_declined(patch_supabase_client, agent_runs):
    _db(patch_supabase_client)
    out = await da.respond_to_offer(R, 10, ORDER, False)
    assert out.result == da.DECLINED and da.whatsapp_reply(out) is None and agent_runs == []
    payload, filters = _updates(patch_supabase_client)[-1]
    assert payload["status"] == "declined" and filters == {"eq:dispatch_id": 10, "in:status": ["unassigned", "accepted"]}


async def test_accepting_an_unassigned_order_marks_the_offer_accepted(patch_supabase_client, agent_runs):
    _db(patch_supabase_client)
    out = await da.respond_to_offer(R, 10, ORDER, True)
    assert out.result == da.ACCEPTED and da.whatsapp_reply(out) is None
    assert _updates(patch_supabase_client) == [({"status": "accepted"}, {"eq:dispatch_id": 10})]


@pytest.mark.parametrize("status, result", [("completed", da.GONE), ("timedout", da.GONE), ("assigned", da.IGNORED)])
async def test_accepting_a_closed_order(patch_supabase_client, agent_runs, status, result):
    _db(patch_supabase_client, summary=({"status": status},))
    out = await da.respond_to_offer(R, 10, ORDER, True)
    assert out.result == result and _updates(patch_supabase_client) == []


async def test_record_offer_ref(patch_supabase_client):
    await da.record_offer_ref(10, None)
    assert patch_supabase_client.calls == []
    await da.record_offer_ref(10, "tg:555:7")
    assert _updates(patch_supabase_client) == [({"channel_msg_ref": "tg:555:7"}, {"eq:dispatch_id": 10, "is:channel_msg_ref": "null"})]


async def test_close_open_offers_edits_only_open_telegram_offers(patch_supabase_client):
    patch_supabase_client.register(table="delivery_dispatch", verb="select", response=FakeSupabaseResponse(data=[
        {"dispatch_id": 1, "rider_id": "A", "status": "unassigned", "channel": "telegram", "channel_msg_ref": "tg:1:10"},
        {"dispatch_id": 2, "rider_id": "B", "status": "assigned", "channel": "telegram", "channel_msg_ref": "tg:2:20"},
        {"dispatch_id": 3, "rider_id": "C", "status": "declined", "channel": "telegram", "channel_msg_ref": "tg:3:30"},
        {"dispatch_id": 4, "rider_id": "D", "status": "unassigned", "channel": "telegram", "channel_msg_ref": None},
    ]))
    patch_supabase_client.register(table="rider_master", verb="select", response=FakeSupabaseResponse(data=[{"channel": "telegram", "tcid": 1}]))
    fake = RecordingRiderMessenger(channel="telegram")
    with use_messenger(fake):
        edited = await da.close_open_offers(ORDER, "taken", winner_dispatch_id=2)
    assert edited == 2
    assert [(kw["ref"], kw["reason"]) for _, kw in fake.calls] == [("tg:1:10", "taken"), ("tg:2:20", "assigned")]
    select = next(c for c in patch_supabase_client.calls if c.table == "delivery_dispatch")
    assert select.filters == {"eq:order_number": ORDER, "eq:channel": "telegram"}  # WhatsApp offers are never touched


async def test_close_open_offers_keeps_going_after_one_failure(patch_supabase_client):
    patch_supabase_client.register(table="delivery_dispatch", verb="select", response=FakeSupabaseResponse(data=[
        {"dispatch_id": 1, "rider_id": "A", "status": "accepted", "channel": "telegram", "channel_msg_ref": "tg:1:10"},
        {"dispatch_id": 2, "rider_id": "B", "status": "unassigned", "channel": "telegram", "channel_msg_ref": "tg:2:20"},
    ]))

    class Flaky(RecordingRiderMessenger):
        async def offer_closed(self, ref, order_number, reason):
            if ref == "tg:1:10":
                raise RuntimeError("telegram down")
            await super().offer_closed(ref, order_number, reason)

    fake = Flaky(channel="telegram")
    with use_messenger(fake):
        assert await da.close_open_offers(ORDER, "expired", statuses=("unassigned", "accepted")) == 1
    assert [kw["ref"] for _, kw in fake.calls] == ["tg:2:20"]
