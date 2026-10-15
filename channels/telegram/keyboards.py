"""Keyboard builders shared by Ordelo Telegram bots.

Reply keyboards (request_contact / request_location) produce plain MESSAGES, not callback
queries, and work in private chats only.
"""

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .callbacks import InviteDecision


def contact_request_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📞 Share my phone number", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def invite_confirm_kb(code: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Yes, link this chat", callback_data=InviteDecision(code=code, action="y").pack())
    b.button(text="❌ No", callback_data=InviteDecision(code=code, action="n").pack())
    b.adjust(1, 1)
    return b.as_markup()
