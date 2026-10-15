"""Tests for utils_common.order_management.restaurant_decision (the shared accept/decline/pickup rule).

The database is replaced by FakeDecisionDb, which mimics the RPC contract of
ordelo_datamodels/migrations/restaurant_order_decision.sql (same result vocabulary, same first-wins rule).
The SQL itself is verified in tests/sql/test_restaurant_decision_sql.py.

Key Functions:
  - test_decide_*            decide() mapping of every RPC result
  - test_set_pickup_*        set_pickup() mapping of every RPC result
  - test_describe_*          wording of the "already decided" reply
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from utils_common.order_management import restaurant_decision as rd


# ---- decide --------------------------------------------------------------------------------------


async def test_decide_accept_ok(decision_db):
    decision_db.add()
    out = await rd.decide("ELAS-ABCD-1", "delivery", "accept", "447700900123", "whatsapp")
    assert out == rd.DecisionOutcome(result="ok", decision="accept", decided_by="…0123", decided_by_phone="447700900123")
    assert decision_db.calls == [("restaurant_order_decide", {
        "p_order_number": "ELAS-ABCD-1", "p_order_type": "delivery", "p_decision": "accept",
        "p_admin_phone": "447700900123", "p_channel": "whatsapp"})]


async def test_decide_decline_ok(decision_db):
    decision_db.add(kind="takeaway")
    out = await rd.decide("ELAS-ABCD-1", "takeaway", "decline", "447700900123", "telegram")
    assert out.result == "ok" and out.decision == "decline"
    assert decision_db.orders[("takeaway", "ELAS-ABCD-1")]["status"] == "declined"


async def test_decide_second_caller_loses_and_learns_who_won(decision_db):
    decision_db.labels["447700900123"] = "Ada"
    decision_db.add()
    await rd.decide("ELAS-ABCD-1", "delivery", "accept", "447700900123", "whatsapp")
    out = await rd.decide("ELAS-ABCD-1", "delivery", "decline", "447700900999", "whatsapp")
    assert out.result == "already_decided" and out.state == "restaurant_accept"
    assert out.decided_by == "Ada" and out.decided_by_phone == "447700900123"
    assert rd.describe(out.state, out.decided_by) == "accepted by Ada"


async def test_decide_not_found(decision_db):
    out = await rd.decide("NOPE-1", "delivery", "accept", "447700900123", "whatsapp")
    assert out.result == "not_found"


@pytest.mark.parametrize("decision,kind", [("maybe", "delivery"), ("accept", "pizza")])
async def test_decide_rejects_bad_arguments_before_calling_the_db(decision_db, decision, kind):
    with pytest.raises(ValueError):
        await rd.decide("ELAS-ABCD-1", kind, decision, "447700900123", "whatsapp")
    assert decision_db.calls == []


async def test_decide_rejects_unexpected_rpc_shape(monkeypatch):
    class Bad:
        def rpc(self, name, args=None):
            return type("Q", (), {"execute": lambda s: SimpleNamespace(data=None)})()

    monkeypatch.setattr(rd, "client_ordelo_service", Bad())
    with pytest.raises(RuntimeError):
        await rd.decide("ELAS-ABCD-1", "delivery", "accept", "447700900123", "whatsapp")


async def test_decide_rejects_unknown_result(monkeypatch):
    class Odd:
        def rpc(self, name, args=None):
            return type("Q", (), {"execute": lambda s: SimpleNamespace(data={"result": "surprise"})})()

    monkeypatch.setattr(rd, "client_ordelo_service", Odd())
    with pytest.raises(RuntimeError):
        await rd.decide("ELAS-ABCD-1", "delivery", "accept", "447700900123", "whatsapp")


# ---- set_pickup ----------------------------------------------------------------------------------


async def test_set_pickup_ok_then_already_set(decision_db):
    decision_db.add(rcs="restaurant_accept")
    out = await rd.set_pickup("ELAS-ABCD-1", "delivery", "2026-10-15T12:15:00+01:00", "447700900123", "whatsapp")
    assert out.result == "ok" and out.pickup_time == "2026-10-15T12:15:00+01:00"
    again = await rd.set_pickup("ELAS-ABCD-1", "delivery", "2026-10-15T12:25:00+01:00", "447700900999", "whatsapp")
    assert again.result == "already_set" and again.decided_by_phone == "447700900123"
    assert decision_db.calls[0][1]["p_pickup_time"] == "2026-10-15T12:15:00+01:00"


async def test_set_pickup_accepts_datetime(decision_db):
    decision_db.add(rcs="restaurant_accept")
    when = datetime(2026, 10, 15, 11, 15, tzinfo=timezone.utc)
    out = await rd.set_pickup("ELAS-ABCD-1", "delivery", when, "447700900123", "telegram")
    assert out.result == "ok"
    assert decision_db.calls[0][1]["p_pickup_time"] == "2026-10-15T11:15:00+00:00"


@pytest.mark.parametrize("state", ["restaurant_unconfirmed", "restaurant_decline", "restaurant_timedout", "auto_accept"])
async def test_set_pickup_requires_accepted_order(decision_db, state):
    decision_db.add(rcs=state)
    out = await rd.set_pickup("ELAS-ABCD-1", "delivery", "2026-10-15T12:15:00+01:00", "447700900123", "whatsapp")
    assert out.result == "not_accepted" and out.state == state


async def test_set_pickup_not_found_and_naive_datetime_rejected(decision_db):
    out = await rd.set_pickup("NOPE-1", "delivery", "2026-10-15T12:15:00+01:00", "447700900123", "whatsapp")
    assert out.result == "not_found"
    with pytest.raises(ValueError):
        await rd.set_pickup("NOPE-1", "delivery", datetime(2026, 10, 15, 12, 15), "447700900123", "whatsapp")


# ---- describe ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state,by,expected",
    [
        ("restaurant_accept", "Ada", "accepted by Ada"),
        ("restaurant_pickuptime_adjusted", "Ada", "accepted by Ada"),
        ("restaurant_accept", None, "accepted"),
        ("restaurant_decline", "…0123", "declined by …0123"),
        ("restaurant_decline", None, "declined"),
        ("restaurant_timedout", None, "auto-accepted (no answer in time)"),
        ("auto_accept", "Ada", "auto-accepted (no answer in time)"),
        ("auto_decline", None, "auto-declined"),
        ("restaurant_unconfirmed", None, "decided"),
        ("something_new", None, "decided"),
    ],
)
def test_describe(state, by, expected):
    assert rd.describe(state, by) == expected
