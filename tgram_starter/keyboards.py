"""Keyboard builders + typed callback data. Callback data is limited to 64 BYTES."""
from typing import Literal

from aiogram.filters.callback_data import CallbackData
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class DemoOrder(CallbackData, prefix="ord"):
    """Packs to e.g. 'ord:1042:a' - compact, typed, parsed back automatically."""
    order_id: int
    action: Literal["a", "d"]  # accept / decline


class Counter(CallbackData, prefix="cnt"):
    value: int
    delta: int


def main_menu():
    b = InlineKeyboardBuilder()
    b.button(text="📦 Demo order offer", callback_data="demo:order")
    b.button(text="🔢 Counter (edits in place)", callback_data=Counter(value=0, delta=0).pack())
    b.button(text="📍 Ask for location", callback_data="demo:location")
    b.button(text="📞 Share my phone", callback_data="demo:contact")
    b.button(text="🌐 URL button", url="https://core.telegram.org/bots/api")
    b.button(text="🖼 Send a photo", callback_data="demo:photo")
    b.adjust(1, 1, 2, 2)
    return b.as_markup()


def order_offer(order_id: int):
    b = InlineKeyboardBuilder()
    b.button(text="✅ Accept", callback_data=DemoOrder(order_id=order_id, action="a").pack())
    b.button(text="❌ Decline", callback_data=DemoOrder(order_id=order_id, action="d").pack())
    b.adjust(2)
    return b.as_markup()


def counter_kb(value: int):
    b = InlineKeyboardBuilder()
    b.button(text="➖", callback_data=Counter(value=value, delta=-1).pack())
    b.button(text=str(value), callback_data=Counter(value=value, delta=0).pack())
    b.button(text="➕", callback_data=Counter(value=value, delta=1).pack())
    b.button(text="⬅ Back", callback_data="demo:menu")
    b.adjust(3, 1)
    return b.as_markup()


def location_request_kb():
    # Reply keyboards produce plain MESSAGES (not callbacks). Private chats only.
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Share current location", request_location=True)]],
        resize_keyboard=True, one_time_keyboard=True,
    )


def contact_request_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📞 Share my phone number", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True,
    )
