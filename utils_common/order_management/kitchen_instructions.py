"""What the kitchen is told about an accepted order (pure: no I/O or channel markup).

Delivery: hold until a rider accepts, start on the kitchen receipt, stop when no rider is found.
Takeaway: never held; start on the kitchen receipt as soon as the pickup time is set.
Callers decide WHEN from existing statuses/events; this module decides WHAT is said.
Telegram escapes/bolds it (order_cards, receipts, restaurant_notifier); WhatsApp adds its own markup
(wa_senders, on_callback_wa_handler). Overview: CONTEXT.md "Kitchen instruction" and ADR 0015.
Functions/classes: KitchenInstruction, hold, start, no_rider.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from utils_common.tz_utils import fmt_uk_time

OrderType = Literal["delivery", "takeaway"]


@dataclass(frozen=True)
class KitchenInstruction:
    headline: str
    detail: str


def hold(order_type: OrderType) -> KitchenInstruction | None:
    """Delivery accepted, no rider yet. Takeaway is never held."""
    if order_type != "delivery":
        return None
    return KitchenInstruction("⏳ Don't start cooking yet — we're finding a rider.", "Start when the kitchen receipt arrives.")


def start(order_type: OrderType, pickup_at: datetime | str | None) -> KitchenInstruction:
    """The go signal, using the current pickup time (including +10 / +20 adjustments)."""
    at = fmt_uk_time(pickup_at) if pickup_at else None
    if order_type == "delivery":
        detail = f"Rider found · ready for pickup at {at}" if at else "Rider found"
    else:
        detail = f"Ready for collection at {at}" if at else "Get it ready for collection"
    return KitchenInstruction("🍳 Please start preparing now", detail)


def no_rider(order_number: str) -> KitchenInstruction:
    """No receipt will follow: the delivery is cancelled."""
    return KitchenInstruction(f"❌ No rider found for {order_number}.", "The order is cancelled — please don't prepare it.")
