"""Rider bot router factory (@ByteloopRidersBot, bot_key 'rider'). Phase R1: onboarding, /help, /whoami.

Onboarding (plans/telegram-rider-bot-plan.md, D39-D42), one generic link for everybody, no per-phone invites:

    /start (any payload, e.g. t.me/ByteloopRidersBot?start=join)
      already linked, profile complete -> "Welcome back"            already linked, town/vehicle 'TBD' -> next choice
      not linked -> "Share my phone number" button (request_contact)
    contact message
      contact.user_id != from_user.id -> refused (a forwarded or typed contact proves nothing)            D39
      else t_rider_link(): linked | already_linked | relinked (ops alert) | registered (ops alert) | tuid_taken (ops alert)
                           | bad_phone                                                                   D42
      registered / still 'TBD' -> town buttons -> vehicle buttons (t_rider_choices(), t_rider_set_profile())
      -> "Thanks, Ordelo will activate your account" (status stays 'inactive' until an operator activates)    D41

No state is kept in the process (gunicorn workers, concurrent updates: telegram_webhook.py): after the contact step
every call is keyed by the tapping person's from_user.id, and the database decides. The phone never travels in
callback data. Plain text is NOT passed to the rider agent in R1; from phase R4 the router sends a rider's text to
their single active dispatch thread (D46, D47).
"""

from __future__ import annotations

import asyncio
from html import escape as _html_escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from loguru import logger

from config.tgram_setting import TgramBotSettings

from .. import rider_links
from ..callbacks import RiderSignup
from ..keyboards import contact_request_kb, rider_choice_kb
from ..replies import answer_quietly
from .commands import HELP_TEXT


def escape(text: str | None) -> str:
    return _html_escape(text or "", quote=False)


TROUBLE = "Sorry, something went wrong on our side. Please try again in a minute."
PRIVATE_ONLY = "Please message me in a private chat."
ASK_PHONE = (
    "Hi! This is the Byteloop riders bot.\n"
    "To link your rider account, tap <b>Share my phone number</b> below."
)
NOT_YOUR_CONTACT = (
    "Please use the <b>Share my phone number</b> button to share your OWN number. "
    "Forwarded or typed contacts can't be used."
)
BAD_PHONE = "That number doesn't look like a mobile number we can use. Please contact Ordelo."
TUID_TAKEN = "This Telegram account is already linked to another rider. Please contact Ordelo."
ASK_TOWN = "Which town will you ride in?"
ASK_VEHICLE = "What will you ride?"
NO_CHOICES = "We can't finish sign-ups right now. Ordelo has been told and will contact you."
OPTION_GONE = "That option isn't available any more. Please pick again."
NOT_LINKED = "Please send /start first to link your rider account."


def linked_text(link: rider_links.RiderLink | rider_links.RiderProfile, again: bool = False) -> str:
    name = escape(link.rider_name)
    head = f"✅ You're already linked, {name}." if again else f"✅ You're linked, {name}."
    if link.status == "active":
        return head + "\nYou'll get your rider messages here."
    return head + "\nYour account is waiting for activation by Ordelo. We'll message you here."


def done_text(link: rider_links.RiderLink, name: str | None) -> str:
    where = f"{escape(link.town)} ({escape(link.vehicle_type)})"
    if link.status == "active":
        return f"✅ All set, {escape(name)}: {where}."
    return f"✅ Thanks {escape(name)}! You're registered for {where}.\nOrdelo will activate your account and message you here."


async def alert_ops(text: str) -> None:
    """One line to the overwatch WhatsApp numbers (existing WALogger). Never raises: an alert must not break onboarding."""
    try:
        from config.params import get_wa_logger

        wa_logger = await get_wa_logger()
        await asyncio.wait_for(wa_logger.info(text), timeout=10)
    except Exception:
        logger.exception(f"telegram[rider]: ops alert failed: {text}")


def _mask(phone: str | None) -> str:
    return f"…{phone[-4:]}" if phone else "?"


# ---- /start --------------------------------------------------------------------------------------------------------
async def cmd_start(message: Message, tgram_settings: TgramBotSettings):
    if message.chat.type != "private":
        await message.answer(PRIVATE_ONLY)
        return
    user = message.from_user
    try:
        prof = await rider_links.profile(user.id)
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: /start profile lookup failed for user {user.id}")
        await message.answer(TROUBLE)
        return
    if not prof.is_linked:
        await message.answer(ASK_PHONE, reply_markup=contact_request_kb())
        return
    if prof.needs_profile:
        await ask_next_choice(message, prof.town, prof.vehicle_type)
        return
    await message.answer(linked_text(prof, again=True))


# ---- contact share -------------------------------------------------------------------------------------------------
async def on_contact(message: Message, tgram_settings: TgramBotSettings):
    if message.chat.type != "private":
        await message.answer(PRIVATE_ONLY)
        return
    user, contact = message.from_user, message.contact
    if contact.user_id is None or contact.user_id != user.id:
        await message.answer(NOT_YOUR_CONTACT, reply_markup=contact_request_kb())
        return
    try:
        out = await rider_links.link(user.id, message.chat.id, contact.phone_number, user.username, user.first_name)
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: link failed for user {user.id}")
        await message.answer(TROUBLE, reply_markup=ReplyKeyboardRemove())
        return

    who = f"@{user.username}" if user.username else (user.first_name or str(user.id))
    if out.result == "tuid_taken":
        await message.answer(TUID_TAKEN, reply_markup=ReplyKeyboardRemove())
        await alert_ops(f"Rider bot: Telegram {who} ({user.id}) shared {_mask(contact.phone_number)} but is already "
                        f"linked to rider {_mask(out.rider_id)}. Refused; please check.")
        return
    if out.result == "bad_phone":
        await message.answer(BAD_PHONE, reply_markup=ReplyKeyboardRemove())
        return
    if out.result == "registered":
        await alert_ops(f"Rider bot: new sign-up {out.rider_name} ({out.rider_id}, Telegram {who}). "
                        "Status inactive; activate when ready.")
        await message.answer(f"Welcome, {escape(out.rider_name)}!", reply_markup=ReplyKeyboardRemove())
        await ask_next_choice(message, out.town, out.vehicle_type)
        return
    if out.result == "relinked":
        prev = f"@{out.previous_username}" if out.previous_username else str(out.previous_tuid)
        await alert_ops(f"Rider bot: rider {out.rider_id} re-linked from Telegram {prev} to {who}.")
    if out.needs_profile:
        await message.answer(f"Hi {escape(out.rider_name)}!", reply_markup=ReplyKeyboardRemove())
        await ask_next_choice(message, out.town, out.vehicle_type)
        return
    await message.answer(linked_text(out, again=out.result == "already_linked"), reply_markup=ReplyKeyboardRemove())


async def ask_next_choice(message: Message, town: str | None, vehicle_type: str | None) -> None:
    """Show the next sign-up question (town first, then vehicle) as buttons from t_rider_choices()."""
    try:
        options = await rider_links.choices()
    except Exception:
        logger.exception("telegram[rider]: t_rider_choices failed")
        await message.answer(TROUBLE)
        return
    step, values, question = (
        ("t", options.towns, ASK_TOWN) if (town or "TBD") == "TBD" else ("v", options.vehicle_types, ASK_VEHICLE)
    )
    kb = rider_choice_kb(step, values)
    if not kb.inline_keyboard:
        await message.answer(NO_CHOICES)
        await alert_ops(f"Rider bot: no {'towns' if step == 't' else 'vehicle types'} to offer a sign-up "
                        "(t_rider_choices() is empty).")
        return
    await message.answer(question, reply_markup=kb)


# ---- sign-up choices -----------------------------------------------------------------------------------------------
async def on_signup_choice(query: CallbackQuery, callback_data: RiderSignup, tgram_settings: TgramBotSettings):
    answered = asyncio.create_task(answer_quietly(query))
    try:
        await _apply_choice(query, callback_data, tgram_settings)
    finally:
        await answered


async def _edit(query: CallbackQuery, text: str, reply_markup=None) -> None:
    if isinstance(query.message, Message):
        try:
            await query.message.edit_text(text, reply_markup=reply_markup)
            return
        except TelegramBadRequest:
            pass
    await query.bot.send_message(query.from_user.id, text, reply_markup=reply_markup)


async def _apply_choice(query: CallbackQuery, data: RiderSignup, tgram_settings: TgramBotSettings) -> None:
    user = query.from_user
    try:
        out = await rider_links.set_profile(
            user.id, town=data.v if data.s == "t" else None, vehicle_type=data.v if data.s == "v" else None
        )
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: set_profile failed for user {user.id}")
        await _edit(query, TROUBLE)
        return
    if out.result == "not_linked":
        await _edit(query, NOT_LINKED)
        return
    if out.result == "locked":
        await _edit(query, f"Your town and vehicle are already set ({escape(out.town)}, {escape(out.vehicle_type)}). "
                           "Contact Ordelo to change them.")
        return
    if out.result in ("bad_town", "bad_vehicle"):
        await _edit(query, OPTION_GONE)
        prof = await rider_links.profile(user.id)
        if isinstance(query.message, Message):
            await ask_next_choice(query.message, prof.town, prof.vehicle_type)
        return
    if out.needs_profile:
        options = await rider_links.choices()
        await _edit(query, f"Town: <b>{escape(out.town)}</b>\n{ASK_VEHICLE}", rider_choice_kb("v", options.vehicle_types))
        return
    prof = await rider_links.profile(user.id)
    await _edit(query, done_text(rider_links.RiderLink(result="ok", town=out.town, vehicle_type=out.vehicle_type,
                                                        status=prof.status), prof.rider_name or user.first_name))


# ---- help, whoami, fallback ----------------------------------------------------------------------------------------
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT)


async def cmd_whoami(message: Message, tgram_settings: TgramBotSettings):
    u = message.from_user
    try:
        prof = await rider_links.profile(u.id)
        if prof.is_linked:
            link_line = (f"rider {escape(prof.rider_id)} ({escape(prof.rider_name)}), {escape(prof.status)}, "
                         f"{escape(prof.town)} / {escape(prof.vehicle_type)}, channel {escape(prof.channel)}")
        else:
            link_line = "not linked (send /start)"
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: /whoami lookup failed for user {u.id}")
        link_line = "unavailable (try again)"
    lines = [
        f"from_user.id (the person): <code>{u.id}</code>",
        f"chat.id (where we reply):  <code>{message.chat.id}</code>",
        f"username (mutable):        @{escape(u.username or '-')}",
        f"Rider link: {link_line}",
    ]
    await message.answer("<pre>" + "\n".join(lines) + "</pre>")


async def fallback(message: Message):
    try:
        prof = await rider_links.profile(message.from_user.id)
    except Exception:
        prof = None
    if prof is not None and prof.is_linked:
        await message.answer("Nothing to do here yet. Your rider messages will arrive in this chat. Try /help.")
    else:
        await message.answer(NOT_LINKED)


def build_router() -> Router:
    """A NEW Router each call: aiogram routers can join only one parent Dispatcher."""
    router = Router(name="rider")
    router.message.register(cmd_start, CommandStart())
    router.message.register(cmd_help, Command("help"))
    router.message.register(cmd_whoami, Command("whoami"))
    router.message.register(on_contact, F.contact)
    router.callback_query.register(on_signup_choice, RiderSignup.filter())
    router.message.register(fallback, F.text)  # last: swallows any other text (R4 routes linked riders' text to the agent)
    return router
