"""Restaurant bot, alert pauses (phase R6; ADR 0013, D51, D52): /off (with the length buttons) and /on.

    /off           -> per linked restaurant: alerts on, or paused until <time>; [6 hours] [1 day] [3 days]  (t_admin_pause_status)
    tap ap1:<key>  -> channels.telegram.admin_pauses.pause(): one pause per restaurant the person is an admin of
                      paused | extended -> "⏸ <restaurant>: paused until <time>"
                      not_allowed      -> "🔔 <restaurant>: not paused, you're the only admin left getting alerts" (D52)
    /on            -> admin_pauses.resume(): "🔔 <restaurant>: alerts back on"
While paused, NEW Telegram order cards, kitchen receipts and notices for that restaurant skip this person
(t_alert_destinations()); cards already in the chat keep updating and their buttons keep working. WhatsApp alerts are not
affected. The pause ends by itself at its end time; job_pause_sweep() sends "starts again soon" and "back on"
(watomation/routers/pause_hooks.py).
Authorisation: the tapping person's from_user.id (D14) -> claimed invites -> admin phone (t_order_admin_phone); callback data
carries only the duration key.
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
from ordelo.pauses import ends_text

from .. import admin_pauses
from ..callbacks import AdminPause
from ..inbox import process_once
from ..keyboards import pause_duration_kb
from ..replies import answer_quietly
from .order_cards.model import TROUBLE

NOT_LINKED = "This chat isn't linked to a restaurant yet, so there are no alerts to pause."
OFF_DISABLED = "Pausing alerts isn't available right now. Please contact Ordelo."
ASK_LENGTH = "Pause new order alerts here for how long?"
TELEGRAM_ONLY = "<i>This pauses Telegram alerts only. Cards already here keep updating.</i>"
OPTION_GONE = "That option isn't available any more. Send /off to pick again."
COME_BACK = "Send /on to turn alerts back on early."


def escape(text) -> str:
    return _html_escape(str(text or ""), quote=False)


def _state_line(r: admin_pauses.RestaurantPause) -> str:
    if r.paused and r.ends_at is not None:
        return f"⏸ <b>{escape(r.rest_name)}</b>: paused until {escape(ends_text(r.ends_at))}"
    return f"🔔 <b>{escape(r.rest_name)}</b>: alerts on"


def pause_result_line(r: admin_pauses.RestaurantPause) -> str:
    name = f"<b>{escape(r.rest_name)}</b>"
    if r.result in ("paused", "extended") and r.ends_at is not None:
        return f"⏸ {name}: paused until {escape(ends_text(r.ends_at))}"
    if r.result == "not_allowed":
        return f"🔔 {name}: not paused. You're the only admin left getting its alerts."
    if r.result == "not_admin":
        return f"🔔 {name}: not paused. You're not one of its admins any more."
    return f"🔔 {name}: not paused."


async def cmd_off(message: Message, tgram_settings: TgramBotSettings):
    try:
        st = await admin_pauses.status(tgram_settings.bot_key, message.from_user.id)
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: /off failed for user {message.from_user.id}")
        await message.answer(TROUBLE)
        return
    if not st.is_linked:
        await message.answer(NOT_LINKED)
        return
    kb = pause_duration_kb(list(st.options), admin=True)
    if not kb.inline_keyboard:
        await message.answer(OFF_DISABLED)
        return
    lines = [ASK_LENGTH, *(_state_line(r) for r in st.restaurants), TELEGRAM_ONLY]
    await message.answer("\n".join(lines), reply_markup=kb)


async def _edit(query: CallbackQuery, text: str) -> None:
    if isinstance(query.message, Message):
        try:
            await query.message.edit_text(text, reply_markup=None)
            return
        except TelegramBadRequest:
            pass
    await query.bot.send_message(query.from_user.id, text)


async def on_pause_tap(query: CallbackQuery, callback_data: AdminPause, tgram_settings: TgramBotSettings, event_update: Update):
    # Protected by the inbox (a redelivered tap must not start a break again after /on): see channels/telegram/inbox.py
    answered = asyncio.create_task(answer_quietly(query))
    try:
        await process_once(
            tgram_settings.bot_key, event_update, query.from_user.id,
            lambda: _handle_pause_tap(query, callback_data, tgram_settings),
        )
    finally:
        await answered


async def _handle_pause_tap(query: CallbackQuery, callback_data: AdminPause, tgram_settings: TgramBotSettings):
    try:
        out = await admin_pauses.pause(tgram_settings.bot_key, query.from_user.id, callback_data.k)
        logger.info(f"telegram[{tgram_settings.bot_key}]: /off {callback_data.k} by {query.from_user.id}: "
                    + ", ".join(f"{r.rest_ref} {r.result}" for r in out.restaurants))
        if not out.is_linked:
            await _edit(query, NOT_LINKED)
            return
        if all(r.result == "bad_duration" for r in out.restaurants):
            await _edit(query, OPTION_GONE)
            return
        lines = [pause_result_line(r) for r in out.restaurants]
        if any(r.result in ("paused", "extended") for r in out.restaurants):
            lines.append(COME_BACK)
        await _edit(query, "\n".join(lines))
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: pause tap failed for user {query.from_user.id}")
        await _edit(query, TROUBLE)


async def cmd_on(message: Message, tgram_settings: TgramBotSettings):
    try:
        out = await admin_pauses.resume(tgram_settings.bot_key, message.from_user.id)
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: /on failed for user {message.from_user.id}")
        await message.answer(TROUBLE)
        return
    if not out.is_linked:
        await message.answer(NOT_LINKED)
        return
    lines = [
        f"🔔 <b>{escape(r.rest_name)}</b>: {'alerts back on' if r.result == 'resumed' else 'alerts were already on'}"
        for r in out.restaurants
    ]
    await message.answer("\n".join(lines))


def build_pauses_router() -> Router:
    """A NEW Router each call. Included by rest_admin/router.py before its text fallback."""
    router = Router(name="rest_admin_pauses")
    router.message.register(cmd_off, Command("off"))
    router.message.register(cmd_on, Command("on"))
    router.callback_query.register(on_pause_tap, AdminPause.filter())
    return router
