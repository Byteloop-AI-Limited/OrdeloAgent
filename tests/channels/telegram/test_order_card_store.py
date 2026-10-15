"""CardStore: RPC names, argument names and response parsing (the contract with the SQL functions)."""

import pytest

from channels.telegram.rest_admin.order_cards.model import Destination, OrderRef
from channels.telegram.rest_admin.order_cards.store import CardStore

from .conftest import FakeResp

ORDER = OrderRef("ELAS-CEKT-22", "delivery")


class FakeRpcClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def rpc(self, name, args):
        self.calls.append((name, args))
        data = self.responses[name]
        return type("Q", (), {"execute": lambda self_: FakeResp(data)})()


@pytest.fixture
def client(monkeypatch):
    def make(responses):
        c = FakeRpcClient(responses)
        monkeypatch.setattr("channels.telegram.rest_admin.order_cards.store.client_ordelo_service", c)
        return c

    return make


SNAP = {
    "status": "accepted", "rest_ref": "ELAS",
    "facts": {"order_number": "ELAS-CEKT-22", "order_type": "delivery", "rest_name": "Elas", "total": "£5.00",
              "items": ["1x Naan"], "ordered_at": "2026-01-15T12:00:00+00:00"},
    "decided_by": {"label": "Ada", "phone": "447700900001"}, "pickup_at": None,
    "destinations": [{"tcid": 111, "tuid": 111, "phone": "447700900001", "label": "Ada"}],
}


async def test_snapshot(client):
    c = client({"t_order_card_snapshot": SNAP})
    snap = await CardStore("rest_admin").snapshot(ORDER)
    assert c.calls == [("t_order_card_snapshot", {"p_bot_key": "rest_admin", "p_order_number": "ELAS-CEKT-22", "p_order_type": "delivery"})]
    assert snap.status == "accepted" and snap.rest_ref == "ELAS" and snap.decided_by.label == "Ada"


async def test_snapshot_none_and_garbage(client):
    client({"t_order_card_snapshot": None})
    assert await CardStore("rest_admin").snapshot(ORDER) is None
    client({"t_order_card_snapshot": "oops"})
    with pytest.raises(RuntimeError):
        await CardStore("rest_admin").snapshot(ORDER)


async def test_card_sent(client):
    c = client({"t_order_card_sent": {"previous": [{"id": 4, "tcid": 111, "message_id": 9}], "order_status": "awaiting"}})
    rec = await CardStore("rest_admin").card_sent(ORDER, "ELAS", Destination(111, 111, "x", "Ada"), 10, "awaiting")
    assert c.calls[0][1] == {"p_bot_key": "rest_admin", "p_tcid": 111, "p_message_id": 10, "p_tuid": 111,
                             "p_order_number": "ELAS-CEKT-22", "p_order_type": "delivery", "p_rest_ref": "ELAS",
                             "p_card_status": "awaiting"}
    assert rec.order_status == "awaiting" and [(p.id, p.message_id, p.taken_for) for p in rec.previous] == [(4, 9, "delete")]


async def test_take_for_refresh(client):
    client({"t_order_cards_take": {"rows": [
        {"id": 1, "tcid": 111, "message_id": 5, "tuid": 111, "viewer_phone": "447700900001", "authorised": True, "taken_for": "edit"},
        {"id": 2, "tcid": -100, "message_id": 6, "tuid": None, "viewer_phone": None, "authorised": False, "taken_for": "delete"}]}})
    rows = await CardStore("rest_admin").take_for_refresh(ORDER)
    assert [(r.id, r.tuid, r.authorised, r.taken_for) for r in rows] == [(1, 111, True, "edit"), (2, None, False, "delete")]


async def test_mark(client):
    c = client({"t_order_card_mark": None})
    await CardStore("rest_admin").mark(7, "edited", "accepted", False)
    assert c.calls == [("t_order_card_mark", {"p_id": 7, "p_outcome": "edited", "p_card_status": "accepted", "p_close": False})]


async def test_decide_and_set_pickup(client):
    c = client({
        "t_order_decide": {"result": "already_decided", "state": "restaurant_decline", "decided_by": "Bob", "decided_by_phone": "447700900002"},
        "t_order_set_pickup": {"result": "ok", "pickup_time": "2026-01-15T12:15:00+00:00", "decided_by": "Ada", "decided_by_phone": "447700900001"},
    })
    s = CardStore("rest_admin")
    out = await s.decide(111, ORDER, "accept")
    assert c.calls[0] == ("t_order_decide", {"p_bot_key": "rest_admin", "p_tuid": 111, "p_order_number": "ELAS-CEKT-22",
                                              "p_order_type": "delivery", "p_decision": "accept"})
    assert (out.result, out.action, out.status, out.by.label) == ("already_decided", "acc", "declined", "Bob")
    out = await s.set_pickup(111, ORDER, 15)
    assert c.calls[1] == ("t_order_set_pickup", {"p_bot_key": "rest_admin", "p_tuid": 111, "p_order_number": "ELAS-CEKT-22",
                                                 "p_order_type": "delivery", "p_minutes": 15})
    assert out.result == "ok" and out.pickup_at.minute == 15


@pytest.mark.parametrize("bad", [None, {}, {"result": "weird"}, "x"])
async def test_garbage_tap_response_raises(client, bad):
    client({"t_order_decide": bad})
    with pytest.raises(RuntimeError):
        await CardStore("rest_admin").decide(1, ORDER, "accept")
