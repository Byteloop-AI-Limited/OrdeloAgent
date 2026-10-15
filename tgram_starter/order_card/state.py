"""Order state shown on the card, and the only allowed ways to change it.

Real code: OrderCardState.load() reads delivery_summary + food order + rider from the DB (Supabase REST calls
wrapped in asyncio.to_thread), and transitions become DB updates guarded on the current status.
"""
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Literal


class CardStatus(str, Enum):
    # Demo names. Real code maps these from delivery_summary.status (restaurant_unconfirmed, assigned, ...).
    NEW = "new"
    PREPARING = "preparing"
    READY = "ready"
    PICKED_UP = "picked_up"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


FINAL = {CardStatus.DELIVERED, CardStatus.CANCELLED}

# Button actions (restaurant admin taps). Short codes: they travel inside 64-byte callback data.
Action = Literal["acc", "dec", "rdy", "d10", "d20", "can", "iss"]
# Delivery events (hooks / jobs elsewhere in the system).
Event = Literal["rider_assigned", "picked_up", "delivered", "cancelled"]


@dataclass(frozen=True)
class OrderLine:
    name: str
    qty: int
    unit_price: float


@dataclass(frozen=True)
class OrderCardState:
    ref: str
    restaurant: str
    status: CardStatus
    items: tuple[OrderLine, ...]
    pickup_time: datetime  # timezone-aware
    customer_address: str
    customer_phone: str
    confirmation_code: str
    rider_name: str | None = None
    rider_phone: str | None = None
    live_url: str | None = None
    last_change: str | None = None  # e.g. "Accepted by Lohith" - shown under the status line
    version: int = field(default=0, compare=False)  # bumped on every change; real code: updated_at

    @property
    def total(self) -> float:
        return sum(i.qty * i.unit_price for i in self.items)


# action -> (statuses it is valid in, resulting status or None to keep the status)
ACTIONS: dict[str, tuple[set[CardStatus], CardStatus | None]] = {
    "acc": ({CardStatus.NEW}, CardStatus.PREPARING),
    "dec": ({CardStatus.NEW}, CardStatus.CANCELLED),
    "d10": ({CardStatus.PREPARING}, None),
    "d20": ({CardStatus.PREPARING}, None),
    "rdy": ({CardStatus.PREPARING}, CardStatus.READY),
    "can": ({CardStatus.PREPARING}, CardStatus.CANCELLED),
    "iss": ({CardStatus.READY, CardStatus.PICKED_UP}, None),
}
EVENTS: dict[str, tuple[set[CardStatus], CardStatus | None]] = {
    "rider_assigned": ({CardStatus.NEW, CardStatus.PREPARING, CardStatus.READY}, None),
    "picked_up": ({CardStatus.READY, CardStatus.PREPARING}, CardStatus.PICKED_UP),
    "delivered": ({CardStatus.PICKED_UP}, CardStatus.DELIVERED),
    "cancelled": (set(CardStatus) - FINAL, CardStatus.CANCELLED),
}
_ACTION_LABEL = {"acc": "Accepted", "dec": "Declined", "d10": "Pickup +10 min", "d20": "Pickup +20 min",
                 "rdy": "Marked ready", "can": "Cancelled", "iss": "Problem reported"}


def apply_action(s: OrderCardState, action: str, actor: str) -> OrderCardState | None:
    """New state after a button tap, or None if the tap is stale (the order already moved on)."""
    valid_in, to = ACTIONS[action]
    if s.status not in valid_in:
        return None
    changes: dict = {"last_change": f"{_ACTION_LABEL[action]} by {actor}", "version": s.version + 1}
    if to:
        changes["status"] = to
    if action in ("d10", "d20"):
        changes["pickup_time"] = s.pickup_time + timedelta(minutes=int(action[1:]))
    return replace(s, **changes)


def apply_event(s: OrderCardState, event: str, **data) -> OrderCardState | None:
    """New state after a delivery event, or None if it doesn't apply in the current status."""
    valid_in, to = EVENTS[event]
    if s.status not in valid_in:
        return None
    changes: dict = {"version": s.version + 1, "last_change": None}
    if to:
        changes["status"] = to
    if event == "rider_assigned":
        changes.update(rider_name=data["rider_name"], rider_phone=data.get("rider_phone"))
    if event == "picked_up":
        changes["live_url"] = data.get("live_url")
    return replace(s, **changes)


# ---- Fake DB --------------------------------------------------------------------------------------
ORDERS: dict[str, OrderCardState] = {}


async def load_order(ref: str) -> OrderCardState | None:
    return ORDERS.get(ref)


async def save_order(s: OrderCardState) -> None:
    ORDERS[s.ref] = s


def demo_order(ref: str = "DEMO-ORDR-21") -> OrderCardState:
    return OrderCardState(
        ref=ref, restaurant="Kitchen", status=CardStatus.NEW,
        items=(OrderLine("Vegetable Biryani", 1, 12.56), OrderLine("Mango Lassi", 1, 2.70),
               OrderLine("Garlic Naan", 2, 3.20), OrderLine("Paneer Tikka", 1, 7.95),
               OrderLine("Onion Bhaji", 1, 4.50), OrderLine("Raita", 1, 1.95)),
        pickup_time=datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=15),
        customer_address="1 Demo Street, Salisbury SP1 3TA", customer_phone="+447700900456",
        confirmation_code="39",
    )
