"""In-memory fake of the kitchen-action RPCs (Ready and adjust pickup).

Mimics the contract of ordelo_datamodels/migrations/restaurant_ready_adjust_notices.sql: same result vocabulary,
same rules (first Ready per dispatch wins; a repeat adjust to the same time is 'unchanged'). The SQL itself is
verified in tests/sql/test_restaurant_ready_adjust_notices_sql.py; change this fake in the same commit whenever the
RPC contract changes.

Key Functions:
  - FakeActionsDb - rpc(name, args) -> object with .execute() -> response with .data
  - actions_db - pytest fixture wiring the fake into utils_common.order_management.restaurant_actions
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest


class _Resp:
    def __init__(self, data):
        self.data = data


def _iso(value) -> str:
    return value.isoformat() if isinstance(value, datetime) else value


class FakeActionsDb:
    """In-memory mimic of restaurant_order_ready / restaurant_order_adjust_pickup and their t_ wrappers."""

    def __init__(self):
        self.orders: dict[tuple[str, str], dict] = {}
        self.calls: list[tuple[str, dict]] = []
        self.labels: dict[str, str] = {}
        self.telegram_admins: dict[tuple[str, int], str] = {}   # (bot_key, tuid) -> admin phone (D14)
        self.fail_with: Exception | None = None

    def add(self, number="ELAS-ABCD-1", kind="delivery", *, rider="RIDER01", dispatch_id=10, dispatch_status="assigned",
            pickup="2026-10-15T12:00:00+00:00", status="pickup_confirmed", rest_name="Elai", recipient="4474"):
        o = dict(rest_name=rest_name, pickup=pickup, initial=None, ready_at=None, ready_by=None, ready_dispatch_id=None,
                 adjusted_by=None, recipient=recipient)
        if kind == "delivery":
            o["inflight"] = None if rider is None else dict(dispatch_id=dispatch_id, rider_id=rider, status=dispatch_status)
        else:
            o["status"] = status
        self.orders[(kind, number)] = o

    def _label(self, phone):
        return self.labels.get(phone) or (f"…{phone[-4:]}" if phone else None)

    def _ready(self, a):
        kind, number, phone = a["p_order_type"], a["p_order_number"], a["p_admin_phone"]
        if kind not in ("delivery", "takeaway"):
            raise ValueError("bad order type")
        o = self.orders.get((kind, number))
        if o is None:
            return {"result": "not_found"}
        if kind == "delivery":
            inf = o["inflight"]
            if inf is None or inf["status"] in ("pickedup", "completed"):
                return {"result": "not_ready_state", "progress": "not_in_progress" if inf is None else "picked_up"}
            if o["ready_dispatch_id"] == inf["dispatch_id"]:
                return self._already(o)
            o.update(ready_at="2026-10-15T12:01:00+00:00", ready_by=phone, ready_dispatch_id=inf["dispatch_id"])
            return {"result": "ok", "rider_id": inf["rider_id"], "dispatch_id": inf["dispatch_id"], "rest_name": o["rest_name"],
                    "ready_by": self._label(phone), "ready_by_phone": phone}
        if o["status"] != "pickup_confirmed":
            return self._already(o) if o["ready_at"] else {"result": "not_ready_state", "progress": "not_in_progress"}
        if o["ready_at"]:
            return self._already(o)
        o.update(ready_at="2026-10-15T12:01:00+00:00", ready_by=phone)
        return {"result": "ok", "rest_name": o["rest_name"], "customer_id": "447700900001", "recipient": o["recipient"],
                "order_id": "-".join(number.split("-")[1:]), "ready_by": self._label(phone), "ready_by_phone": phone}

    def _already(self, o):
        return {"result": "already_ready", "ready_at": o["ready_at"], "ready_by": self._label(o["ready_by"]),
                "ready_by_phone": o["ready_by"]}

    def _adjust(self, a):
        number, phone, target = a["p_order_number"], a["p_admin_phone"], _iso(a["p_target"])
        o = self.orders.get(("delivery", number))
        if o is None:
            return {"result": "not_found"}
        inf = o["inflight"]
        if inf is None or inf["status"] in ("pickedup", "completed"):
            return {"result": "not_ready_state", "progress": "not_in_progress" if inf is None else "picked_up"}
        if o["pickup"] == target:
            return {"result": "unchanged", "pickup_time": o["pickup"]}
        o.update(initial=o["initial"] or o["pickup"], pickup=target, adjusted_by=phone)
        return {"result": "ok", "pickup_time": target, "by": self._label(phone), "by_phone": phone}

    def _t_wrap(self, a, shared, shared_args):
        o = self.orders.get((a.get("p_order_type", "delivery"), a["p_order_number"]))
        if o is None:
            return {"result": "not_found"}
        phone = self.telegram_admins.get((a["p_bot_key"], a["p_tuid"]))
        if phone is None:
            return {"result": "not_authorised"}
        return shared({**shared_args, "p_admin_phone": phone})

    def _t_ready(self, a):
        return self._t_wrap(a, self._ready, {"p_order_number": a["p_order_number"], "p_order_type": a["p_order_type"]})

    def _t_adjust(self, a):
        if a["p_minutes"] not in (10, 20):
            raise ValueError("bad minutes")
        o = self.orders.get(("delivery", a["p_order_number"]))
        if o is None:
            return {"result": "not_found"}
        base = datetime.fromisoformat(o["initial"] or o["pickup"]) + timedelta(minutes=a["p_minutes"])
        return self._t_wrap(a, self._adjust, {"p_order_number": a["p_order_number"], "p_target": base.isoformat()})

    def rpc(self, name, args=None):
        self.calls.append((name, args))
        if self.fail_with is not None:
            raise self.fail_with
        fn = {"restaurant_order_ready": self._ready, "restaurant_order_adjust_pickup": self._adjust,
              "t_order_ready": self._t_ready, "t_order_adjust_pickup": self._t_adjust}[name]
        data = fn(args or {})
        return type("Q", (), {"execute": lambda self_: _Resp(data)})()


@pytest.fixture
def actions_db(monkeypatch):
    db = FakeActionsDb()
    monkeypatch.setattr("utils_common.order_management.restaurant_actions.client_ordelo_service", db)
    return db
