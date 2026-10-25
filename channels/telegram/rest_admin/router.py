"""Restaurant-admin bot router factory: deterministic commands only, never a LangGraph agent.

Linking flow (plans/restaurant-admin-roster-onboarding-plan.md, D2, D5, D6): /start asks for the phone with Telegram's
"Share my phone number" button; the router accepts the contact ONLY when contact.user_id == from_user.id (the number is the
sender's own), then t_admin_link() decides: linked | relinked (ops alert) | already_linked | not_on_roster (ops alert) |
tuid_taken (ops alert) | bad_phone. Typed or forwarded numbers are never accepted. Linking moves the admin's alerts to Telegram
only; /channels (channels.py) changes that. Invite links are retired (TRANSITION, removed in P3): an old "Link this chat?"
button gets a "not used any more" answer and an old claimed invite is told to share its number once.
Order buttons: orders.py. Alert pauses (/off, /on, phase R6 of
plans/telegram-rider-bot-plan.md): pauses.py. The text fallback is a sub-router included LAST, because aiogram tries a
router's own handlers before its included routers (a fallback registered here would swallow /off and /on).
"""

import asyncio
from html import escape as _html_escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove, Update
from loguru import logger

from config.tgram_setting import TgramBotSettings

from .. import admin_links, invites  # invites: TRANSITION (P3 removes), only to spot an old claimed invite
from ..callbacks import InviteDecision  # TRANSITION (P3 removes): old "Link this chat?" messages still have buttons
from ..inbox import process_once
from ..keyboards import contact_request_kb
from ..ops_alerts import alert_ops, mask
from ..replies import answer_quietly
from .channels import build_channels_router
from .commands import HELP_TEXT
from .order_cards.model import TROUBLE
from .orders import build_orders_router
from .pauses import build_pauses_router



def escape(text: str) -> str:
    """Escape user/DB text for Telegram HTML (only & < > matter; quotes are fine in text nodes)."""
    return _html_escape(text, quote=False)


PRIVATE_ONLY = "Please message me in a private chat."
ASK_PHONE = (
    "Hi! This is the Ordelo restaurant bot.\n"
    "To get your restaurant's order alerts here, tap <b>Share my phone number</b> below."
)
NOT_YOUR_CONTACT = (
    "Please use the <b>Share my phone number</b> button to share your OWN number. "
    "Forwarded or typed contacts can't be used."
)
NOT_ON_ROSTER = (
    "This number isn't set up as a restaurant admin. Ask your Ordelo contact to add it, then send /start again."
)
NO_LONGER_ADMIN = "This number isn't on any restaurant's admin list any more. Ask your Ordelo contact if that's wrong."
TUID_TAKEN = "This Telegram account is already linked to another admin. Please contact Ordelo."
BAD_PHONE = "That number doesn't look like a mobile number we can use. Please contact Ordelo."
INVITE_RETIRED = "Invite links aren't used any more. Tap <b>Share my phone number</b> below to link this chat."
LEGACY_LINKED = (
    "You're linked through an old invite link. Tap <b>Share my phone number</b> below to switch to the new link; "
    "old invite links stop working soon."
)
CHANNEL_LABELS = {("telegram",): "Telegram", ("whatsapp",): "WhatsApp", ("telegram", "whatsapp"): "Telegram and WhatsApp"}


def restaurants_text(restaurants) -> str:
    return "\n".join(f"• {escape(r.rest_name)} ({escape(r.rest_ref)})" for r in restaurants)


def linked_text(out, again: bool) -> str:
    head = "✅ You're already linked." if again else "✅ You're linked."
    where = CHANNEL_LABELS.get(tuple(sorted(out.channels)), ", ".join(out.channels))
    return f"{head}\n{restaurants_text(out.restaurants)}\nOrder alerts: <b>{escape(where)}</b>. Change with /channels."


# ---- /start --------------------------------------------------------------------------------------------------------
async def cmd_start(message: Message, command: CommandObject, tgram_settings: TgramBotSettings):
    if message.chat.type != "private":
        await message.answer(PRIVATE_ONLY)
        return
    user = message.from_user
    try:
        prof = await admin_links.profile(user.id)
        legacy = [] if prof.result != "not_linked" else await invites.linked_restaurants(tgram_settings.bot_key, user.id)
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: /start profile lookup failed for user {user.id}")
        await message.answer(TROUBLE)
        return
    if prof.is_admin:
        await message.answer(linked_text(prof, again=True))
    elif prof.result == "not_on_roster":
        await message.answer(NO_LONGER_ADMIN)
    elif legacy:  # TRANSITION (P3 removes)
        await message.answer(LEGACY_LINKED, reply_markup=contact_request_kb())
    elif command.args and command.args.strip() not in ("", "admin"):
        await message.answer(INVITE_RETIRED, reply_markup=contact_request_kb())
    else:
        await message.answer(ASK_PHONE, reply_markup=contact_request_kb())


# ---- contact share -------------------------------------------------------------------------------------------------
async def on_contact(message: Message, tgram_settings: TgramBotSettings, event_update: Update):
    if message.chat.type != "private":
        await message.answer(PRIVATE_ONLY)
        return
    user, contact = message.from_user, message.contact
    if contact.user_id is None or contact.user_id != user.id:
        await message.answer(NOT_YOUR_CONTACT, reply_markup=contact_request_kb())
        return
    await process_once(tgram_settings.bot_key, event_update, user.id, lambda: _link_contact(message, tgram_settings))


async def _link_contact(message: Message, tgram_settings: TgramBotSettings):
    user, contact = message.from_user, message.contact
    try:
        out = await admin_links.link(user.id, message.chat.id, contact.phone_number, user.username, user.first_name)
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: admin link failed for user {user.id}")
        await message.answer(TROUBLE, reply_markup=ReplyKeyboardRemove())
        return
    who = f"@{user.username}" if user.username else (user.first_name or str(user.id))
    if out.result == "not_on_roster":
        await message.answer(NOT_ON_ROSTER, reply_markup=ReplyKeyboardRemove())
        await alert_ops(f"Restaurant bot: Telegram {who} ({user.id}) shared {mask(contact.phone_number)}, which is on no "
                        "restaurant's admin list. Refused; add it in sys-admin if they should be an admin.")
        return
    if out.result == "tuid_taken":
        await message.answer(TUID_TAKEN, reply_markup=ReplyKeyboardRemove())
        await alert_ops(f"Restaurant bot: Telegram {who} ({user.id}) shared {mask(contact.phone_number)} but is already "
                        f"linked to admin …{out.phone_last4 or '?'}. Refused; please check.")
        return
    if not out.is_linked:  # bad_phone, or a result this code does not know
        await message.answer(BAD_PHONE, reply_markup=ReplyKeyboardRemove())
        return
    if out.result == "relinked":
        prev = f"@{out.previous_username}" if out.previous_username else str(out.previous_tuid)
        await alert_ops(f"Restaurant bot: admin {mask(out.phone)} re-linked from Telegram {prev} to {who}.")
    await message.answer(linked_text(out, again=out.result == "already_linked"), reply_markup=ReplyKeyboardRemove())


# ---- old invite buttons (TRANSITION, P3 removes) -------------------------------------------------------------------
async def _finish(query: CallbackQuery, text: str) -> None:
    """Replace the confirmation message (buttons removed); fall back to a new message."""
    if isinstance(query.message, Message):
        try:
            await query.message.edit_text(text, reply_markup=None)
            return
        except TelegramBadRequest:
            pass
    await query.bot.send_message(query.from_user.id, text)


async def on_invite_decision(query: CallbackQuery, callback_data: InviteDecision, tgram_settings: TgramBotSettings):
    """An old "Link this chat?" button. Nothing is claimed any more: the person is pointed at the contact share."""
    answered = asyncio.create_task(answer_quietly(query))
    try:
        await _finish(query, "Invite links aren't used any more.")
        await query.bot.send_message(query.from_user.id, INVITE_RETIRED, reply_markup=contact_request_kb())
    finally:
        await answered


async def cmd_help(message: Message):
    await message.answer(HELP_TEXT)


async def cmd_whoami(message: Message, tgram_settings: TgramBotSettings):
    u = message.from_user
    try:
        prof = await admin_links.profile(u.id)
        legacy = [] if prof.result != "not_linked" else await invites.linked_restaurants(tgram_settings.bot_key, u.id)
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: /whoami lookup failed for user {u.id}")
        prof, legacy = None, None
    channels_line = "-"
    if prof is None:
        link_line = "unavailable (try again)"
    elif prof.is_admin:
        link_line = ", ".join(f"{r.rest_name} ({r.rest_ref})" for r in prof.restaurants)
        channels_line = CHANNEL_LABELS.get(tuple(sorted(prof.channels)), ", ".join(prof.channels))
    elif prof.result == "not_on_roster":
        link_line = "linked, but this number is on no admin list"
    elif legacy:  # TRANSITION (P3 removes)
        link_line = ", ".join(f"{r.rest_name} ({r.rest_ref})" for r in legacy) + " (old invite: share your number to switch)"
        channels_line = "Telegram (old invite)"
    else:
        link_line = "not linked"
    lines = [
        f"from_user.id (the person): <code>{u.id}</code>",
        f"chat.id (where we reply):  <code>{message.chat.id}</code>",
        f"username (mutable):        @{escape(u.username or '-')}",
        f"Ordelo link: {escape(link_line)}",
        f"Order alerts: {escape(channels_line)}",
    ]
    await message.answer("<pre>" + "\n".join(lines) + "</pre>")


async def fallback(message: Message):
    await message.answer("I don't understand that yet. Try /help.")


def build_router() -> Router:
    """A NEW Router each call: aiogram routers can join only one parent Dispatcher."""
    router = Router(name="rest_admin")
    router.message.register(cmd_start, CommandStart())
    router.message.register(on_contact, F.contact)
    router.message.register(cmd_help, Command("help"))
    router.message.register(cmd_whoami, Command("whoami"))
    router.callback_query.register(on_invite_decision, InviteDecision.filter())  # TRANSITION (P3 removes)
    router.include_router(build_orders_router())  # order-card buttons (callback queries; the text fallback is a message handler)
    router.include_router(build_pauses_router())  # R6: /off (+ length taps), /on
    router.include_router(build_channels_router())  # /channels + its 'ac1:' buttons
    last = Router(name="rest_admin_fallback")  # last: swallows any other text
    last.message.register(fallback, F.text)
    router.include_router(last)
    return router
