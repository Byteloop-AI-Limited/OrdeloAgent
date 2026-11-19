"""Restaurant bot, sys-admin link: /sysadmin and the "System dashboard" button under /manage (overwatch members only).

    /sysadmin or tap 'sa1:go' -> dashboard_links.issue("sys_admin", Actor(tuid=from_user.id))
                              -> RPC sys_admin_dashboard_mint (admin_dashboard/auth_sessions.sql): linked record +
                                 is_overwatch(phone) checked in the same transaction as the insert
                              -> one URL button "Open system dashboard" (30 minutes, works once)
Twin of WhatsApp `/sysadmin` (watomation/on_message_wa_handler.py handle_sysadmin_wa_msg). The button carries no identity:
an old button tapped by someone removed from overwatch gets "operations only". A refused request also clears this chat's
scoped menu (menu.py) so /sysadmin stops being advertised. Private chats only; previews off; the URL is never logged.
"""

from __future__ import annotations

import asyncio

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Message
from loguru import logger

from config.tgram_setting import TgramBotSettings
from ordelo.dashboard_links import Actor, access, issue

from ..callbacks import SysAdminLink
from ..replies import answer_quietly
from .menu import sync_admin_menu
from .order_cards.model import TROUBLE

PRIVATE_ONLY = "Please message me in a private chat."
OPS_ONLY = "The system dashboard is for Ordelo operations only."
NOT_LINKED = "This chat isn't linked yet. Send /start and share your phone number first."
INTRO = (
    "Ordelo system dashboard.\n"
    "<i>The link expires in 30 minutes and works once. Send /sysadmin again for a new one.</i>"
)
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def sysadmin_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Open system dashboard", url=url)]])


async def send_sysadmin_link(message: Message, tuid: int, tgram_settings: TgramBotSettings) -> None:
    """Mint and send the link to this private chat, or explain why not. Shared by the command and the button."""
    key = tgram_settings.bot_key
    try:
        out = await issue("sys_admin", Actor(tuid=tuid))
    except Exception:
        logger.warning(f"telegram[{key}]: /sysadmin could not issue a link for user {tuid}")
        await message.answer(TROUBLE)
        return
    if not out.ok:
        await message.answer(NOT_LINKED if out.result == "not_linked" else OPS_ONLY)
        try:
            await sync_admin_menu(message.bot, message.chat.id, await access(Actor(tuid=tuid)))
        except Exception:
            logger.warning(f"telegram[{key}]: /sysadmin menu reconcile failed for user {tuid}")
        return
    url = out.links[0].url
    logger.info(f"telegram[{key}]: sent a sys-admin dashboard link to user {tuid}")
    try:
        await message.answer(INTRO, reply_markup=sysadmin_keyboard(url), link_preview_options=NO_PREVIEW)
    except TelegramBadRequest:  # e.g. BUTTON_URL_INVALID for a non-public dashboard URL
        logger.warning(f"telegram[{key}]: sys-admin button refused; sending the link as text")
        await message.answer(INTRO + "\n\n" + url, link_preview_options=NO_PREVIEW)


async def cmd_sysadmin(message: Message, tgram_settings: TgramBotSettings):
    if message.chat.type != "private":
        await message.answer(PRIVATE_ONLY)
        return
    await send_sysadmin_link(message, message.from_user.id, tgram_settings)


async def on_sysadmin_tap(query: CallbackQuery, callback_data: SysAdminLink, tgram_settings: TgramBotSettings):
    # Acknowledge beside the real work: a failed or slow answer (expired query) must not stop the link (replies.py).
    answered = asyncio.create_task(answer_quietly(query))
    try:
        if query.message is not None and query.message.chat.type == "private":
            await send_sysadmin_link(query.message, query.from_user.id, tgram_settings)
    finally:
        await answered


def build_sysadmin_router() -> Router:
    """A NEW Router each call. Included by rest_admin/router.py before its text fallback."""
    router = Router(name="rest_admin_sysadmin")
    router.message.register(cmd_sysadmin, Command("sysadmin"))
    router.callback_query.register(on_sysadmin_tap, SysAdminLink.filter())
    return router
