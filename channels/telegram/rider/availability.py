"""Rider bot, availability (phase R5; ADR 0013, D41, D51, D53): /shift, /off (with the break-length buttons), /on.

Telegram riders are ON by default: no daily shift question (that exists only because of WhatsApp's 24-hour window). They step
away for a fixed time and come back early if they want:

    /off            -> "Take a break from new job offers for how long?"  [6 hours] [1 day] [3 days]   (pause_options('rider'))
    tap rp1:<key>   -> ordelo.pauses.pause('rider', rider_id, key): paused | extended (a second /off replaces the end time)
                       -> the question is edited to "⏸ On a break until <time>" (and "your current job carries on")
    /on             -> ordelo.pauses.resume() + ordelo.rider_shift.set_shift(rider_id, True) (the status gate, D41)
    /shift          -> status: account not active yet | on a break until <time> | on | off shift; the current job, if any
An inflight row blocks /off, /on and old pause buttons. Telegram's private-chat menu also hides /off and /on during
the job; /shift reconciles that menu. The pause ends by itself at its end time (is_paused() reads the clock);
job_pause_sweep() only sends "ends soon" and "back on" (watomation/routers/pause_hooks.py).
Authorisation: the tapping person's from_user.id -> rider_master.tuid -> rider_id (rider_links.profile); callback data carries
only the duration key. A rider who is not active cannot take a break (there is nothing to step away from).
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
from ordelo import pauses, rider_shift
from ordelo.agents import rider_threads

from .. import rider_links
from ..callbacks import RiderPause
from ..inbox import process_once
from ..keyboards import pause_duration_kb
from ..replies import answer_quietly
from .commands import set_inflight_menu

NOT_LINKED = "Please send /start first to link your rider account."
TROUBLE = "Sorry, something went wrong on our side. Please try again in a minute."
NOT_ACTIVE = "Your rider account is waiting for activation by Byteloop. We'll message you here when it's ready."
ASK_LENGTH = "Take a break from new job offers for how long?"
OFF_DISABLED = "Breaks can't be set here right now. Please contact Byteloop."
OPTION_GONE = "That option isn't available any more. Send /off to pick again."
BACK_ON = "✅ Break over: you're back on. New job offers will arrive here."
ALREADY_ON = "✅ You're on. New job offers arrive here. Send /off to take a break."
OTHER_CHANNEL = "Your job offers currently go to WhatsApp. Please contact Byteloop to move them here."
ON_JOB = "Please complete the current order before using /off or /on."


def escape(text) -> str:
    return _html_escape(str(text or ""), quote=False)


async def _profile(tuid: int) -> rider_links.RiderProfile | None:
    prof = await rider_links.profile(tuid)
    return prof if prof.is_linked else None


async def _job_line(rider_id: str) -> str | None:
    thread = await rider_threads.active_for_rider(rider_id, touch=False)
    if thread is None or not thread.order_number:
        return None
    return f"Current job: <b>{escape(thread.order_number)}</b> (/job)"


def paused_text(ends_at, job_line: str | None = None) -> str:
    lines = [f"⏸ On a break until <b>{escape(pauses.ends_text(ends_at))}</b>. No new job offers until then.",
             "Send /on to come back early."]
    if job_line:
        lines.append(job_line.replace("Current job:", "Your current job") + " carries on.")
    return "\n".join(lines)


# ---- /off ----------------------------------------------------------------------------------------------------------
async def cmd_off(message: Message, tgram_settings: TgramBotSettings):
    try:
        prof = await _profile(message.from_user.id)
        if prof is None:
            await message.answer(NOT_LINKED)
            return
        if prof.status != "active":
            await message.answer(NOT_ACTIVE)
            return
        if await rider_shift.inflight_order(prof.rider_id) is not None:
            if message.chat.type == "private":
                await set_inflight_menu(message.bot, message.chat.id, True)
            await message.answer(ON_JOB)
            return
        if message.chat.type == "private":
            await set_inflight_menu(message.bot, message.chat.id, False)
        keys, current = await asyncio.gather(pauses.options(pauses.RIDER), pauses.current(pauses.RIDER, prof.rider_id))
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: /off failed for user {message.from_user.id}")
        await message.answer(TROUBLE)
        return
    kb = pause_duration_kb(keys)
    if not kb.inline_keyboard:
        await message.answer(OFF_DISABLED)
        return
    text = ASK_LENGTH
    if current is not None:
        text = (f"You're on a break until <b>{escape(pauses.ends_text(current.ends_at))}</b>.\n"
                "Pick a new length (it replaces the current one), or send /on to come back now.")
    await message.answer(text, reply_markup=kb)


async def _edit(query: CallbackQuery, text: str) -> None:
    if isinstance(query.message, Message):
        try:
            await query.message.edit_text(text, reply_markup=None)
            return
        except TelegramBadRequest:
            pass
    await query.bot.send_message(query.from_user.id, text)


async def on_pause_tap(query: CallbackQuery, callback_data: RiderPause, tgram_settings: TgramBotSettings, event_update: Update):
    # Protected by the inbox (a redelivered tap must not start a break again after /on): see channels/telegram/inbox.py
    answered = asyncio.create_task(answer_quietly(query))
    try:
        await process_once(
            tgram_settings.bot_key, event_update, query.from_user.id,
            lambda: _handle_pause_tap(query, callback_data, tgram_settings),
        )
    finally:
        await answered


async def _handle_pause_tap(query: CallbackQuery, callback_data: RiderPause, tgram_settings: TgramBotSettings):
    try:
        prof = await _profile(query.from_user.id)
        if prof is None:
            await _edit(query, NOT_LINKED)
            return
        if prof.status != "active":
            await _edit(query, NOT_ACTIVE)
            return
        if await rider_shift.inflight_order(prof.rider_id) is not None:
            await set_inflight_menu(query.bot, query.from_user.id, True)
            await _edit(query, ON_JOB)
            return
        out = await pauses.pause(pauses.RIDER, prof.rider_id, callback_data.k, via="telegram", by=str(query.from_user.id))
        logger.info(f"telegram[rider]: /off {callback_data.k} by rider {prof.rider_id}: {out.result}")
        if not out.is_paused or out.pause is None:
            await _edit(query, ON_JOB if out.result == "on_job" else OPTION_GONE)
            return
        await _edit(query, paused_text(out.pause.ends_at, await _job_line(prof.rider_id)))
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: pause tap failed for user {query.from_user.id}")
        await _edit(query, TROUBLE)


# ---- /on -----------------------------------------------------------------------------------------------------------
async def cmd_on(message: Message, tgram_settings: TgramBotSettings):
    try:
        prof = await _profile(message.from_user.id)
        if prof is None:
            await message.answer(NOT_LINKED)
            return
        if await rider_shift.inflight_order(prof.rider_id) is not None:
            if message.chat.type == "private":
                await set_inflight_menu(message.bot, message.chat.id, True)
            await message.answer(ON_JOB)
            return
        if message.chat.type == "private":
            await set_inflight_menu(message.bot, message.chat.id, False)
        resumed = await pauses.resume(pauses.RIDER, prof.rider_id)
        if resumed.result == "on_job":
            await message.answer(ON_JOB)
            return
        shift = await rider_shift.set_shift(prof.rider_id, True)
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: /on failed for user {message.from_user.id}")
        await message.answer(TROUBLE)
        return
    logger.info(f"telegram[rider]: /on by rider {prof.rider_id}: pause {resumed.result}, shift {shift.result}")
    if shift.result == rider_shift.NOT_ACTIVE:
        await message.answer(NOT_ACTIVE)
        return
    text = BACK_ON if resumed.result == "resumed" else ALREADY_ON
    if prof.channel != "telegram":
        text += "\n" + OTHER_CHANNEL
    await message.answer(text)


# ---- /shift --------------------------------------------------------------------------------------------------------
async def cmd_shift(message: Message, tgram_settings: TgramBotSettings):
    try:
        prof = await _profile(message.from_user.id)
        if prof is None:
            await message.answer(NOT_LINKED)
            return
        current, job_line, inflight_order = await asyncio.gather(
            pauses.current(pauses.RIDER, prof.rider_id), _job_line(prof.rider_id),
            rider_shift.inflight_order(prof.rider_id),
        )
        if message.chat.type == "private":
            await set_inflight_menu(message.bot, message.chat.id, inflight_order is not None)
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: /shift failed for user {message.from_user.id}")
        await message.answer(TROUBLE)
        return
    lines = [shift_status_text(prof, current, inflight_order is not None)]
    if job_line:
        lines.append(job_line)
    elif inflight_order:
        lines.append(f"Current job: <b>{escape(inflight_order)}</b> (/job)")
    if prof.channel != "telegram":
        lines.append(OTHER_CHANNEL)
    await message.answer("\n".join(lines))


def shift_status_text(prof: rider_links.RiderProfile, current: pauses.Pause | None, inflight: bool = False) -> str:
    """One line: why this rider does or does not get job offers right now (the same gates as get_available_riders())."""
    if prof.status != "active":
        return "⚪ " + NOT_ACTIVE
    if inflight:
        return "🛵 On a delivery. Please complete the current order before changing availability."
    if current is not None:
        return (f"⏸ On a break until <b>{escape(pauses.ends_text(current.ends_at))}</b>. "
                "Send /on to come back early.")
    if not prof.is_in_shift:
        return "⚪ Off shift. Send /on to start getting job offers."
    return "🟢 On: new job offers arrive here. Send /off to take a break."


def build_availability_router() -> Router:
    """A NEW Router each call. Mounted by rider/router.py before its text fallback."""
    router = Router(name="rider_availability")
    router.message.register(cmd_shift, Command("shift"))
    router.message.register(cmd_off, Command("off"))
    router.message.register(cmd_on, Command("on"))
    router.callback_query.register(on_pause_tap, RiderPause.filter())
    return router
