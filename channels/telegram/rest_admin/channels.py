"""Restaurant bot, alert channels (plans/restaurant-admin-roster-onboarding-plan.md, D6): /channels and its three buttons.

    /channels      -> not linked: the "Share my phone number" prompt
                      linked:     "Order alerts now: X. Where should they go?"  [Telegram only] [WhatsApp only] [Both]
    tap ac1:<c>    -> admin_roster.set_channels() for the admin record found by the tapping person's from_user.id (D14)
                      ok -> "✅ Order alerts: X."      not_found / not_linked -> the "Share my phone number" prompt
The choice is stored in restaurant_admin.channels (admin_roster.sql). Telegram alerts follow it at once
(t_alert_destinations()); WhatsApp follows it from phase P2 (WHATSAPP_FOLLOWS_CHANNELS below says so in the text until then).
A pause (/off) silences every channel regardless of this choice. Authority is membership of a restaurant's admin list, not the
channel: an admin who chose WhatsApp only can still tap old cards here.
"""

from __future__ import annotations

import asyncio
from html import escape as _html_escape

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, Update
from loguru import logger

from config.tgram_setting import TgramBotSettings
from ordelo import admin_roster

from .. import admin_links
from ..callbacks import AdminChannels
from ..inbox import process_once
from ..keyboards import CHANNEL_CHOICES, admin_channels_kb, contact_request_kb
from ..replies import answer_quietly
from .order_cards.model import TROUBLE

# Flipped to True in phase P2, when the WhatsApp senders start following restaurant_admin.channels.
WHATSAPP_FOLLOWS_CHANNELS = False

NOT_LINKED = "This chat isn't linked yet. Tap <b>Share my phone number</b> below to link it."
NO_LONGER_ADMIN = "This number isn't on any restaurant's admin list any more. Ask your Ordelo contact if that's wrong."
OPTION_GONE = "That option isn't available any more. Send /channels to pick again."
P1_NOTE = "<i>Telegram follows this at once; WhatsApp will follow it from the next Ordelo update.</i>"
CHANNEL_WORDS = {("telegram",): "Telegram", ("whatsapp",): "WhatsApp", ("telegram", "whatsapp"): "Telegram and WhatsApp"}


def escape(text) -> str:
    return _html_escape(str(text or ""), quote=False)


def channels_label(channels) -> str:
    key = tuple(sorted(channels))
    return CHANNEL_WORDS.get(key, ", ".join(key) or "unknown")


async def cmd_channels(message: Message, tgram_settings: TgramBotSettings):
    if message.chat.type != "private":
        await message.answer("Please message me in a private chat.")
        return
    try:
        prof = await admin_links.profile(message.from_user.id)
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: /channels failed for user {message.from_user.id}")
        await message.answer(TROUBLE)
        return
    if prof.result == "not_linked":
        await message.answer(NOT_LINKED, reply_markup=contact_request_kb())
        return
    if prof.result == "not_on_roster":
        await message.answer(NO_LONGER_ADMIN)
        return
    lines = [f"Order alerts now: <b>{escape(channels_label(prof.channels))}</b>.", "Where should they go?"]
    if not WHATSAPP_FOLLOWS_CHANNELS:
        lines.append(P1_NOTE)
    await message.answer("\n".join(lines), reply_markup=admin_channels_kb())


async def _edit(query: CallbackQuery, text: str) -> None:
    if isinstance(query.message, Message):
        try:
            await query.message.edit_text(text, reply_markup=None)
            return
        except TelegramBadRequest:
            pass
    await query.bot.send_message(query.from_user.id, text)


async def on_channels_tap(
    query: CallbackQuery, callback_data: AdminChannels, tgram_settings: TgramBotSettings, event_update: Update
):
    answered = asyncio.create_task(answer_quietly(query))
    try:
        await process_once(
            tgram_settings.bot_key, event_update, query.from_user.id,
            lambda: _handle_channels_tap(query, callback_data, tgram_settings),
        )
    finally:
        await answered


async def _handle_channels_tap(query: CallbackQuery, callback_data: AdminChannels, tgram_settings: TgramBotSettings):
    uid = query.from_user.id
    choice = CHANNEL_CHOICES.get(callback_data.c)
    if choice is None:
        await _edit(query, OPTION_GONE)
        return
    try:
        prof = await admin_links.profile(uid)
        if not prof.is_admin:
            await _edit(query, NOT_LINKED if prof.result == "not_linked" else NO_LONGER_ADMIN)
            return
        out = await admin_roster.set_channels(prof.phone, choice[1], by=f"telegram:{uid}")
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: channels tap failed for user {uid}")
        await _edit(query, TROUBLE)
        return
    logger.info(f"telegram[{tgram_settings.bot_key}]: /channels {callback_data.c} by {uid}: {out.result}")
    if out.ok:
        text = f"✅ Order alerts: <b>{escape(channels_label(out.channels))}</b>."
        if not WHATSAPP_FOLLOWS_CHANNELS:
            text += "\n" + P1_NOTE
        await _edit(query, text)
    elif out.result in ("not_found", "not_linked"):
        await _edit(query, NOT_LINKED)
    else:
        await _edit(query, OPTION_GONE)


def build_channels_router() -> Router:
    """A NEW Router each call. Included by rest_admin/router.py before its text fallback."""
    router = Router(name="rest_admin_channels")
    router.message.register(cmd_channels, Command("channels"))
    router.callback_query.register(on_channels_tap, AdminChannels.filter())
    return router
