"""Restaurant-admin bot router factory: deterministic commands only, never a LangGraph agent.

Linking flow: the admin opens a private invite link (t.me/<bot>?start=<code>), the bot shows which
restaurant it would link and asks for confirmation, and a tap on Yes claims the invite atomically
(channels/telegram/invites.py). Order actions and acknowledgement come later
(plans/telegram-rest-admin-scaffold-plan.md).
"""

import asyncio
from html import escape as _html_escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message
from loguru import logger

from config.tgram_setting import TgramBotSettings

from .. import invites
from ..callbacks import InviteDecision
from ..keyboards import invite_confirm_kb
from ..replies import answer_quietly
from .commands import HELP_TEXT
from .order_cards.model import TROUBLE
from .orders import build_orders_router



def escape(text: str) -> str:
    """Escape user/DB text for Telegram HTML (only & < > matter; quotes are fine in text nodes)."""
    return _html_escape(text, quote=False)


NOT_LINKED = (
    "Hi! This is the Ordelo restaurant bot.\n"
    "This chat isn't linked to a restaurant yet. Open the invite link you were sent, "
    "or ask your Ordelo contact for a new one."
)
PRIVATE_ONLY = "Please open the invite link in a private chat with this bot."

# Messages for invites that cannot be used.
INVITE_PROBLEMS = {
    "unknown": "That invite link isn't valid. Ask your Ordelo contact for a new one.",
    "used": "That invite link has already been used. Ask your Ordelo contact for a new one.",
    "expired": "That invite link has expired. Ask your Ordelo contact for a new one.",
    "revoked": "That invite link was cancelled. Ask your Ordelo contact for a new one.",
    "already_linked": "This Telegram account is already linked to that restaurant.",
}


ONBOARDED = "✅ You've been onboarded successfully."
ALREADY_ONBOARDED = "✅ You're already onboarded."


async def cmd_start(message: Message, command: CommandObject, tgram_settings: TgramBotSettings):
    if message.chat.type != "private":
        await message.answer(PRIVATE_ONLY)
        return
    bot_key, user_id = tgram_settings.bot_key, message.from_user.id
    try:
        if command.args:
            outcome = await invites.preview_invite(bot_key, command.args.strip(), user_id)
            if outcome.result == "pending":
                await message.answer(
                    f"Link this chat to <b>{escape(outcome.rest_name or outcome.rest_ref or '')}</b>?\n"
                    "You'll receive order alerts for this restaurant here.",
                    reply_markup=invite_confirm_kb(command.args.strip()),
                )
            elif outcome.result == "claimed_by_you":
                await message.answer(ALREADY_ONBOARDED)
            else:
                await message.answer(INVITE_PROBLEMS.get(outcome.result, INVITE_PROBLEMS["unknown"]))
            return

        linked = await invites.linked_restaurants(bot_key, user_id)
    except Exception:
        logger.exception(f"telegram[{bot_key}]: /start failed for user {user_id}")
        await message.answer(TROUBLE)
        return

    if linked:
        names = "\n".join(f"• {escape(r.rest_name)} ({escape(r.rest_ref)})" for r in linked)
        await message.answer(f"Welcome back, {escape(message.from_user.first_name)}.\nLinked to:\n{names}")
    else:
        await message.answer(NOT_LINKED)


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
    # Clear the spinner beside the real work, never before it: a hung answer must not block the claim.
    answered = asyncio.create_task(answer_quietly(query))
    try:
        await _apply_invite_decision(query, callback_data, tgram_settings)
    finally:
        await answered


async def _apply_invite_decision(query: CallbackQuery, callback_data: InviteDecision, tgram_settings: TgramBotSettings):
    bot_key, user = tgram_settings.bot_key, query.from_user
    if callback_data.action == "n":
        await _finish(query, "Okay, this chat is not linked. Your invite link stays valid until it expires.")
        return
    chat_id = query.message.chat.id if isinstance(query.message, Message) else user.id
    try:
        outcome = await invites.claim_invite(
            bot_key,
            callback_data.code,
            user_id=user.id,
            chat_id=chat_id,
            username=user.username,
            first_name=user.first_name,
        )
    except Exception:
        logger.exception(f"telegram[{bot_key}]: invite claim failed for user {user.id}")
        await _finish(query, TROUBLE)
        return
    if outcome.is_linked:
        await _finish(query, ONBOARDED)
    else:
        await _finish(query, INVITE_PROBLEMS.get(outcome.result, INVITE_PROBLEMS["unknown"]))


async def cmd_help(message: Message):
    await message.answer(HELP_TEXT)


async def cmd_whoami(message: Message, tgram_settings: TgramBotSettings):
    u = message.from_user
    try:
        linked = await invites.linked_restaurants(tgram_settings.bot_key, u.id)
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: /whoami lookup failed for user {u.id}")
        linked = None
    if linked is None:
        link_line = "unavailable (try again)"
    elif linked:
        link_line = ", ".join(f"{r.rest_name} ({r.rest_ref})" for r in linked)
    else:
        link_line = "not linked"
    lines = [
        f"from_user.id (the person): <code>{u.id}</code>",
        f"chat.id (where we reply):  <code>{message.chat.id}</code>",
        f"username (mutable):        @{escape(u.username or '-')}",
        f"Ordelo link: {escape(link_line)}",
    ]
    await message.answer("<pre>" + "\n".join(lines) + "</pre>")


async def fallback(message: Message):
    await message.answer("I don't understand that yet. Try /help.")


def build_router() -> Router:
    """A NEW Router each call: aiogram routers can join only one parent Dispatcher."""
    router = Router(name="rest_admin")
    router.message.register(cmd_start, CommandStart())
    router.message.register(cmd_help, Command("help"))
    router.message.register(cmd_whoami, Command("whoami"))
    router.callback_query.register(on_invite_decision, InviteDecision.filter())
    router.include_router(build_orders_router())  # order-card buttons (callback queries; the text fallback is a message handler)
    router.message.register(fallback, F.text)  # last: swallows any other text
    return router
