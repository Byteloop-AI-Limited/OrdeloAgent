"""In-memory mimic of the receipt side of restaurant_ready_adjust_notices.sql, as seen through ReceiptStore.

It shares ONE order state with FakeActionsDb (tests/fixtures/fake_restaurant_actions.py): a Ready or +10 done through
restaurant_actions (WhatsApp or Telegram) changes what the next snapshot says, exactly as the shared tables do in
the database. Same status keys as t_receipt_status; the SQL itself is proven in tests/sql/.
Change this fake in the same commit whenever the SQL functions change.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from channels.telegram.rest_admin.order_cards.model import OrderRef
from channels.telegram.rest_admin.receipts.model import ReceiptDestination, ReceiptSnapshot
from channels.telegram.rest_admin.receipts.store import ReceiptCopy, ReceiptSent

ADA = ReceiptDestination(111, 111, "447700900001", "Ada", reply_to=None)
BOB = ReceiptDestination(222, 222, "447700900002", "Bob", reply_to=None)
LONDON = ZoneInfo("Europe/London")


def hhmi(iso: str | None) -> str:
    from datetime import datetime

    return datetime.fromisoformat(iso).astimezone(LONDON).strftime("%H:%M") if iso else "--:--"


class FakeReceiptStore:
    def __init__(self, actions_db):
        self.db = actions_db                      # FakeActionsDb: the order state shared with restaurant_actions
        self.destinations: list[ReceiptDestination] = [ADA, BOB]
        self.ledger: list[dict] = []
        self.calls: list[str] = []
        self.completed: set[str] = set()           # orders whose summary status is 'completed'
        self.declined: set[str] = set()
        self.fail_snapshot = False
        self._next_id = 1

    # ---- the status key (mirrors t_receipt_status)
    def status(self, order: OrderRef, dispatch_id: int | None) -> str:
        kind, number = order.order_type, order.order_number
        o = self.db.orders.get((kind, number))
        if o is None or number in self.declined:
            return "gone"
        if number in self.completed:
            return "done"
        hm = hhmi(o["pickup"])
        if kind == "takeaway":
            return f"ready@{hm}" if o["ready_at"] else f"open@{hm}"
        inf = o["inflight"]
        if inf is None or inf["dispatch_id"] != dispatch_id:
            return "rider_cancelled"
        if inf["status"] in ("pickedup", "completed"):
            return "picked_up"
        return f"ready@{hm}" if o["ready_dispatch_id"] == dispatch_id else f"open@{hm}"

    def _facts(self, order: OrderRef, dispatch_id: int | None) -> dict:
        o = self.db.orders[(order.order_type, order.order_number)]
        label = lambda p: {"label": self.db.labels.get(p) or f"…{p[-4:]}", "phone": p} if p else None  # noqa: E731
        delivery = order.order_type == "delivery"
        return {
            "order_number": order.order_number, "order_type": order.order_type, "rest_name": o["rest_name"], "rest_code": 47,
            "pickup_at": o["pickup"], "pickup_initial": o["initial"], "pickup_adjusted_by": label(o["adjusted_by"]),
            "ready_at": o["ready_at"], "ready_by": label(o["ready_by"]),
            "rider": {"id": "RIDER01", "name": "Sam"} if delivery else None,
            "customer": {"address": "1 Test Street, Orpington", "phone": "447448440754"} if delivery else None,
            "items": [{"qty": 2, "name": "Chicken Shawarma", "line_total": 17.0, "mods": ["extra garlic sauce"]},
                      {"qty": 1, "name": "Fries", "line_total": 3.5, "mods": []}],
            "small_order_fee": 1.0, "total": 21.5, "notes": "Please ring the bell twice",
            "pay_at_restaurant": False, "completed_at": None,
        }

    # ---- ReceiptStore interface
    async def snapshot(self, order, dispatch_id):
        self.calls.append("snapshot")
        if self.fail_snapshot:
            raise RuntimeError("db down")
        o = self.db.orders.get((order.order_type, order.order_number))
        if o is None:
            return None
        if dispatch_id is None and order.order_type == "delivery" and o["inflight"]:
            dispatch_id = o["inflight"]["dispatch_id"]
        data = {"status": self.status(order, dispatch_id), "rest_ref": "ELAS", "dispatch_id": dispatch_id,
                "facts": self._facts(order, dispatch_id),
                "destinations": [dict(tcid=d.tcid, tuid=d.tuid, phone=d.phone, label=d.label, reply_to=d.reply_to)
                                 for d in self.destinations]}
        return ReceiptSnapshot.from_json(data)

    async def receipt_sent(self, order, rest_ref, dest, message_id, dispatch_id, status):
        self.calls.append("receipt_sent")
        row = dict(id=self._next_id, tcid=dest.tcid, message_id=message_id, tuid=dest.tuid, order=order,
                   dispatch_id=dispatch_id, status=status, state="live", taken_for=None)
        self._next_id += 1
        # Mirrors t_receipt_sent: a copy that was closed as 'edited' (cancelled-rider view) is still on screen and is
        # replaced too; a receipt that is itself cancelled / gone replaces nothing.
        current = self.status(order, dispatch_id)
        previous = [] if current in ("rider_cancelled", "gone") else [
            r for r in self.ledger
            if r["tcid"] == dest.tcid and r["order"] == order
            and (r["state"] == "live" or (r["state"] == "closed" and r.get("close_reason") == "edited"))]
        for r in previous:
            r.update(state="taken", taken_for="delete")
        self.ledger.append(row)
        return ReceiptSent(
            previous=tuple(ReceiptCopy(r["id"], r["tcid"], r["message_id"], taken_for="delete") for r in previous),
            status=self.status(order, dispatch_id),
        )

    def _destination(self, row):
        return next((d for d in self.destinations if d.tcid == row["tcid"]), None)

    async def take_for_refresh(self, order):
        self.calls.append("take_for_refresh")
        out = []
        for r in self.ledger:
            if r["order"] != order or r["state"] != "live":
                continue
            dest = self._destination(r)
            if r["status"] != self.status(order, r["dispatch_id"]) or dest is None:
                r.update(state="taken", taken_for="edit")
                out.append(ReceiptCopy(r["id"], r["tcid"], r["message_id"], r["tuid"], dest.phone if dest else None,
                                       dest is not None, "edit", r["dispatch_id"]))
        return out

    async def mark(self, copy_id, outcome, card_status, close):
        self.calls.append(f"mark:{outcome}")
        r = next(x for x in self.ledger if x["id"] == copy_id)
        if close or outcome in ("deleted", "gone"):
            r.update(state="closed", close_reason=outcome)
        else:
            r.update(state="live", status=card_status or r["status"])

    def live(self):
        return [r for r in self.ledger if r["state"] == "live"]
