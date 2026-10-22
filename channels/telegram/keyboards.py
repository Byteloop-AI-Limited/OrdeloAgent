"""Keyboard builders shared by Ordelo Telegram bots.

Reply keyboards (request_contact / request_location) produce plain MESSAGES, not callback
queries, and work in private chats only.
"""

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .callbacks import InviteDecision, RiderJobAction, RiderOffer, RiderSignup


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


def location_request_kb() -> ReplyKeyboardMarkup:
    """One tap shares the rider's CURRENT location (a plain message with .location; private chats only)."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Share current location", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def rider_choice_kb(step: str, values: list[str]) -> InlineKeyboardMarkup:
    """Sign-up buttons for towns (step 't') or vehicle types (step 'v'), two per row.

    A value that cannot travel in callback data (over 64 bytes packed, or containing ':') is left out;
    t_rider_choices() values are short in practice (town names, 'bike', 'car').
    """
    b = InlineKeyboardBuilder()
    for v in values:
        try:
            packed = RiderSignup(s=step, v=v).pack()  # raises ValueError for ':' in v or more than 64 bytes
        except ValueError:
            continue
        b.button(text=v, callback_data=packed)
    b.adjust(2)
    return b.as_markup()


def rider_offer_kb(dispatch_id: int) -> InlineKeyboardMarkup:
    """Accept / Decline under a job offer (phase R4)."""
    b = InlineKeyboardBuilder()
    b.button(text="✅ Accept", callback_data=RiderOffer(d=dispatch_id, a="a").pack())
    b.button(text="❌ Decline", callback_data=RiderOffer(d=dispatch_id, a="d").pack())
    b.adjust(2)
    return b.as_markup()


def rider_job_card_kb(dispatch_id: int) -> InlineKeyboardMarkup:
    """Pickup Location / Dropoff Location / Contact Customer under the delivery instructions (R3)."""
    from ordelo.rider_messaging.models import JOB_CARD_ACTIONS  # values only; no import cycle at module load

    b = InlineKeyboardBuilder()
    for code in ("pk", "dr", "cc"):
        b.button(text=JOB_CARD_ACTIONS[code][0], callback_data=RiderJobAction(d=dispatch_id, a=code).pack())
    b.adjust(2, 1)
    return b.as_markup()
