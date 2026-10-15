"""Menu + in-memory orders for the demo mini app. Lost on restart. Prices are in pence and ONLY the server
computes totals: the page sends item ids and quantities, never prices."""
import itertools
import threading
import time
from dataclasses import dataclass

MENU = [
    {"id": "marg", "emoji": "🍕", "name": "Margherita pizza", "desc": "Tomato, mozzarella, basil", "price": 850},
    {"id": "pepp", "emoji": "🍕", "name": "Pepperoni pizza", "desc": "Spicy pepperoni, mozzarella", "price": 995},
    {"id": "burg", "emoji": "🍔", "name": "Classic burger", "desc": "Beef patty, cheddar, pickles", "price": 1050},
    {"id": "wrap", "emoji": "🌯", "name": "Falafel wrap", "desc": "Hummus, salad, chilli sauce", "price": 725},
    {"id": "fries", "emoji": "🍟", "name": "Fries", "desc": "Skin-on, sea salt", "price": 350},
    {"id": "cola", "emoji": "🥤", "name": "Cola", "desc": "330ml can", "price": 200},
]
MENU_BY_ID = {m["id"]: m for m in MENU}
MAX_QTY, MAX_LINES = 10, 20

_lock = threading.Lock()
_ids = itertools.count(1001)
ORDERS: dict[str, dict] = {}
_IDEMPOTENT: dict[tuple[int, str], str] = {}  # (user_id, key) -> order_id


class OrderError(ValueError):
    pass


@dataclass
class Line:
    id: str
    qty: int


def _price(lines: list[Line]) -> tuple[list[dict], int]:
    if not lines:
        raise OrderError("empty order")
    if len(lines) > MAX_LINES:
        raise OrderError("too many lines")
    merged: dict[str, int] = {}
    for ln in lines:
        if ln.id not in MENU_BY_ID:
            raise OrderError(f"unknown item {ln.id!r}")
        if not 1 <= ln.qty <= MAX_QTY:
            raise OrderError(f"quantity for {ln.id!r} must be 1-{MAX_QTY}")
        merged[ln.id] = merged.get(ln.id, 0) + ln.qty
    if any(q > MAX_QTY for q in merged.values()):
        raise OrderError(f"quantity must be at most {MAX_QTY} per item")
    items = [{"id": i, "name": MENU_BY_ID[i]["name"], "qty": q, "unit": MENU_BY_ID[i]["price"],
              "line_total": MENU_BY_ID[i]["price"] * q} for i, q in merged.items()]
    return items, sum(it["line_total"] for it in items)


def create_order(user_id: int, lines: list[Line], idempotency_key: str) -> tuple[dict, bool]:
    """Returns (order, created). Same user + same key returns the original order (double-tap safe)."""
    items, total = _price(lines)
    with _lock:
        existing = _IDEMPOTENT.get((user_id, idempotency_key))
        if existing:
            return ORDERS[existing], False
        order_id = f"M{next(_ids)}"
        ORDERS[order_id] = {"id": order_id, "user_id": user_id, "items": items, "total": total, "created_at": time.time()}
        _IDEMPOTENT[(user_id, idempotency_key)] = order_id
        return ORDERS[order_id], True


def status_of(order: dict, now: float | None = None) -> str:
    """Demo only: status advances with elapsed time (a real system reads the delivery state)."""
    age = (now or time.time()) - order["created_at"]
    return "placed" if age < 15 else "preparing" if age < 40 else "ready"


def public_view(order: dict) -> dict:
    return {k: order[k] for k in ("id", "items", "total", "created_at")} | {"status": status_of(order)}


def orders_for(user_id: int) -> list[dict]:
    return [public_view(o) for o in sorted(ORDERS.values(), key=lambda o: -o["created_at"]) if o["user_id"] == user_id]


def get_order_for(user_id: int, order_id: str) -> dict | None:
    """Owner-only. Someone else's order id looks exactly like a missing one."""
    o = ORDERS.get(order_id)
    return public_view(o) if o and o["user_id"] == user_id else None
