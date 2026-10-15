"""Card text + buttons from state. Pure: no I/O, no clock, so every status can be snapshot-tested.

Every value that comes from the DB goes through h() - an address with "&" or "<" would otherwise make
Telegram reject the whole message ("can't parse entities").
"""
from html import escape as h
from zoneinfo import ZoneInfo

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .state import CardStatus, OrderCardState

UK = ZoneInfo("Europe/London")


class CardAction(CallbackData, prefix="card"):
    """Packs to e.g. 'card:DEMO-ORDR-21:acc'. Only ids travel; everything else is reloaded on tap."""
    ref: str
    act: str  # an Action code from state.ACTIONS


STATUS_LINE = {
    CardStatus.NEW: "🆕 <b>New order</b> - please confirm",
    CardStatus.PREPARING: "👨‍🍳 <b>Preparing</b>",
    CardStatus.READY: "🔔 <b>Ready</b> - waiting for rider",
    CardStatus.PICKED_UP: "🛵 <b>Picked up</b> - on the way",
    CardStatus.DELIVERED: "✅ <b>Delivered</b>",
    CardStatus.CANCELLED: "❌ <b>Cancelled</b>",
}

# status -> rows of (label, action). URL buttons are added in render_buttons.
BUTTONS: dict[CardStatus, list[list[tuple[str, str]]]] = {
    CardStatus.NEW: [[("✅ Accept", "acc"), ("❌ Decline", "dec")]],
    CardStatus.PREPARING: [[("🔔 Ready - Notify Rider", "rdy")],
                           [("+10 min", "d10"), ("+20 min", "d20")],
                           [("❌ Cancel order", "can")]],
    CardStatus.READY: [[("⚠️ Report a problem", "iss")]],
    CardStatus.PICKED_UP: [[("⚠️ Report a problem", "iss")]],
}


def _time(s: OrderCardState) -> str:
    # <tg-time> shows the time in the reader's own zone; the inner text is the fallback for older apps.
    return f'<tg-time unix="{int(s.pickup_time.timestamp())}" format="t">{s.pickup_time.astimezone(UK):%H:%M}</tg-time>'


def render_text(s: OrderCardState) -> str:
    items = "\n".join(f"• {i.qty} × {h(i.name)}  -  £{i.unit_price:.2f}" for i in s.items)
    if s.status is CardStatus.CANCELLED:
        items = f"<s>{items}</s>"
    lines = [
        f"<b>Order #{h(s.ref)}</b> ({h(s.restaurant)})",
        f"Status: {STATUS_LINE[s.status]}",
        *([f"<i>{h(s.last_change)}</i>"] if s.last_change else []),
        "",
        f"<blockquote expandable><b>Items ({len(s.items)})</b>\n{items}</blockquote>",
        f"<b>Total:</b> £{s.total:.2f}",
        "",
        "<b>Delivery details</b>",
        f"⏰ Pickup - <b>{_time(s)}</b>",
        f"🛵 Rider - <b>{h(s.rider_name)}</b> {h(s.rider_phone or '')}".rstrip() if s.rider_name else "🛵 Rider - <i>finding a rider…</i>",
        f"🔢 Confirmation code - <tg-spoiler>{h(s.confirmation_code)}</tg-spoiler>",
        f"🏠 Customer - {h(s.customer_address)} {h(s.customer_phone)}",
    ]
    if s.status is CardStatus.PICKED_UP and s.live_url:
        lines.append(f'📍 <a href="{h(s.live_url, quote=True)}">Live location</a>')
    return "\n".join(lines)


def render_buttons(s: OrderCardState) -> InlineKeyboardMarkup | None:
    rows = BUTTONS.get(s.status)
    if not rows:
        return None  # final states: buttons removed
    kb = InlineKeyboardBuilder()
    sizes = []
    for row in rows:
        for label, act in row:
            kb.button(text=label, callback_data=CardAction(ref=s.ref, act=act).pack())
        sizes.append(len(row))
    if s.status is CardStatus.PICKED_UP and s.live_url:
        kb.button(text="📍 Track rider", url=s.live_url)  # URL button: opens the link, no callback
        sizes[-1] += 1
    kb.adjust(*sizes)
    return kb.as_markup()
