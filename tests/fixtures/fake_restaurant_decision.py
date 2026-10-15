"""In-memory fake of the restaurant decision RPCs (restaurant_order_decide / restaurant_order_set_pickup).

Mimics the contract of ordelo_datamodels/migrations/restaurant_order_decision.sql: same result vocabulary,
same first-decision-wins rule. The SQL itself is verified in tests/sql/test_restaurant_decision_sql.py;
change this fake in the same commit whenever the RPC contract changes.

Key Functions:
  - FakeDecisionDb - rpc(name, args) -> object with .execute() -> response with .data
  - decision_db - pytest fixture wiring the fake into utils_common.order_management.restaurant_decision
"""

from __future__ import annotations

import pytest


class _Resp:
    def __init__(self, data):
        self.data = data


class FakeDecisionDb:
    """In-memory mimic of restaurant_order_decide / restaurant_order_set_pickup."""

    def __init__(self):
        self.orders: dict[tuple[str, str], dict] = {}
        self.calls: list[tuple[str, dict]] = []
        self.labels: dict[str, str] = {}

    def add(self, number="ELAS-ABCD-1", kind="delivery", rcs="restaurant_unconfirmed", admin=None, pickup=None):
        self.orders[(kind, number)] = dict(rcs=rcs, status="restaurant_unconfirmed", admin=admin, pickup=pickup)

    def _label(self, phone):
        return self.labels.get(phone) or (f"…{phone[-4:]}" if phone else None)

    def _decide(self, a):
        o = self.orders.get((a["p_order_type"], a["p_order_number"]))
        if a["p_decision"] not in ("accept", "decline"):
            raise ValueError("bad decision")
        if o is None:
            return {"result": "not_found"}
        if o["rcs"] == "restaurant_unconfirmed":
            o.update(rcs="restaurant_accept" if a["p_decision"] == "accept" else "restaurant_decline",
                     admin=a["p_admin_phone"])
            if a["p_decision"] == "decline":
                o["status"] = "declined"
            return {"result": "ok", "decision": a["p_decision"], "channel": a["p_channel"],
                    "decided_by": self._label(a["p_admin_phone"]), "decided_by_phone": a["p_admin_phone"]}
        return {"result": "already_decided", "state": o["rcs"], "decided_by": self._label(o["admin"]),
                "decided_by_phone": o["admin"], "decided_at": "2026-10-15T12:00:00+00:00", "pickup_time": o["pickup"]}

    def _pickup(self, a):
        o = self.orders.get((a["p_order_type"], a["p_order_number"]))
        if o is None:
            return {"result": "not_found"}
        if o["rcs"] == "restaurant_accept" and o["pickup"] is None:
            o.update(pickup=a["p_pickup_time"], admin=a["p_admin_phone"],
                     status="unassigned" if a["p_order_type"] == "delivery" else "pickup_confirmed")
            return {"result": "ok", "pickup_time": a["p_pickup_time"], "decided_by": self._label(a["p_admin_phone"]),
                    "decided_by_phone": a["p_admin_phone"]}
        return {"result": "already_set" if o["pickup"] else "not_accepted", "state": o["rcs"],
                "pickup_time": o["pickup"], "decided_by": self._label(o["admin"]), "decided_by_phone": o["admin"]}

    def rpc(self, name, args=None):
        self.calls.append((name, args))
        fn = {"restaurant_order_decide": self._decide, "restaurant_order_set_pickup": self._pickup}[name]
        data = fn(args or {})
        return type("Q", (), {"execute": lambda self_: _Resp(data)})()




@pytest.fixture
def decision_db(monkeypatch):
    db = FakeDecisionDb()
    monkeypatch.setattr("utils_common.order_management.restaurant_decision.client_ordelo_service", db)
    return db
