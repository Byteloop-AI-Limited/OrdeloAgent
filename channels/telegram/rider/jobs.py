"""Rider bot, job handlers (phase R4): offer taps, job-card taps, /job, and a rider's text to the rider agent.

    ro1:<dispatch_id>:a|d   offer Accept / Decline -> ordelo.dispatch_actions.respond_to_offer (the WhatsApp rules, D48)
                            -> the offer is edited in place to its outcome, buttons removed (D49)
    rj1:<dispatch_id>:pk|dr|cc  job-card buttons -> the rider agent on that dispatch's thread, with the same words a
                            WhatsApp tap gives it (ordelo.rider_messaging.JOB_CARD_ACTIONS)
    /job                    the rider's current job (order, pickup, drop-off) or "no active job"
    text                    linked rider + open thread on Telegram -> the rider agent (run in the background, so a slow
                            LLM turn never hits the 25 s webhook limit); open thread on WhatsApp -> "please reply there"
                            (D44); no open thread -> a fixed line. No AI is used to guess what text means outside a job.
Authorisation (ADR 0011 decision 5): the tapping person's from_user.id -> rider_master.tuid -> rider_id, and the dispatch must
be that rider's. Callback data is never trusted; a chat id authorises nothing. Every decision is re-read from the database.
"""

from __future__ import annotations

import asyncio
from html import escape as _html_escape

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from loguru import logger

from config.tgram_setting import TgramBotSettings
from ordelo import dispatch_actions
from ordelo.agents import rider_threads
from ordelo.rider_messaging import JOB_CARD_ACTIONS, dispatch_channel, tg_ref
from ordelo.rider_messaging.formatting import wa_to_html
from ordelo.rider_messaging.models import wrong_channel_text
from ordelo.rider_messaging.telegram import TelegramRiderMessenger

from .. import rider_links
from ..callbacks import RiderJobAction, RiderOffer
from ..replies import answer_quietly

NOT_LINKED = "Please send /start first to link your rider account."
NOT_YOURS = "This offer isn't for you."
EXPIRED = "This job is expired."
NO_JOB = "No active job right now. New offers will arrive in this chat."
TROUBLE = "Sorry, something went wrong on our side. Please try again in a minute."

# Offer outcome -> how the tapped offer is redrawn (TelegramRiderMessenger.CLOSED_TEXT keys).
OFFER_EDIT = {
    dispatch_actions.ACCEPTED: "accepted",
    dispatch_actions.DECLINED: "declined",
    dispatch_actions.GONE: "gone",
    dispatch_actions.TAKEN: "taken",
    dispatch_actions.ALREADY_ON_THIS_JOB: "assigned",
    dispatch_actions.CANCEL_OWN_JOB: "cancelled",
}

_background: set[asyncio.Task] = set()


def escape(text) -> str:
    return _html_escape(str(text or ""), quote=False)


def spawn(coro, what: str) -> asyncio.Task:
    """Run an agent turn outside the webhook's 25 s budget; keep a reference and log failures."""
    task = asyncio.create_task(coro)
    _background.add(task)

    def done(t: asyncio.Task) -> None:
        _background.discard(t)
        if not t.cancelled() and t.exception() is not None:
            logger.opt(exception=t.exception()).error(f"telegram[rider]: background {what} failed")

    task.add_done_callback(done)
    return task


async def _rider_id(tuid: int) -> str | None:
    prof = await rider_links.profile(tuid)
    return prof.rider_id if prof.is_linked else None


# ---- offer Accept / Decline ----------------------------------------------------------------------------------------
async def on_offer_tap(query: CallbackQuery, callback_data: RiderOffer, tgram_settings: TgramBotSettings):
    try:
        rider_id = await _rider_id(query.from_user.id)
        dc = await dispatch_channel(callback_data.d)
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: offer tap lookup failed")
        await answer_quietly(query, TROUBLE, show_alert=True)
        return
    if rider_id is None:
        await answer_quietly(query, NOT_LINKED, show_alert=True)
        return
    if dc is not None and dc.rider_id != rider_id:
        await answer_quietly(query, NOT_YOURS, show_alert=True)
        return

    answered = asyncio.create_task(answer_quietly(query))
    try:
        chat_id = query.message.chat.id if isinstance(query.message, Message) else query.from_user.id
        here = TelegramRiderMessenger(query.bot, chat_id)
        ref = tg_ref(chat_id, query.message.message_id) if isinstance(query.message, Message) else None
        if dc is None:  # the offer row is gone (order cancelled and re-dispatched, test reset, ...)
            await here.offer_closed(ref, "", "gone")
            return
        out = await dispatch_actions.respond_to_offer(rider_id, dc.dispatch_id, dc.order_number, callback_data.a == "a")
        logger.info(f"telegram[rider]: offer {dc.dispatch_id} tap by {rider_id}: {out.result}")
        reason = OFFER_EDIT.get(out.result)
        if reason:
            await here.offer_closed(ref, out.order_number, reason)
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: offer tap failed for dispatch {callback_data.d}")
    finally:
        await answered


# ---- job-card buttons ----------------------------------------------------------------------------------------------
async def on_job_action(query: CallbackQuery, callback_data: RiderJobAction, tgram_settings: TgramBotSettings):
    try:
        rider_id = await _rider_id(query.from_user.id)
        thread = await rider_threads.for_dispatch(callback_data.d)
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: job action lookup failed")
        await answer_quietly(query, TROUBLE, show_alert=True)
        return
    if rider_id is None:
        await answer_quietly(query, NOT_LINKED, show_alert=True)
        return
    if thread is None or thread.rider_id != rider_id:
        await answer_quietly(query, NOT_YOURS if thread is not None else EXPIRED, show_alert=True)
        return
    if not thread.is_active or thread.dispatch_status == "completed":
        await answer_quietly(query, EXPIRED)
        return
    await answer_quietly(query)
    from ordelo.agents.agent_runner import run_rider_agent_w_custom_msg

    spawn(
        run_rider_agent_w_custom_msg(recipient=rider_id, human_msg=JOB_CARD_ACTIONS[callback_data.a][1],
                                     thread_id=thread.thread_id),
        f"job action {callback_data.a} for dispatch {callback_data.d}",
    )


# ---- /job ----------------------------------------------------------------------------------------------------------
async def cmd_job(message: Message, tgram_settings: TgramBotSettings):
    try:
        rider_id = await _rider_id(message.from_user.id)
        if rider_id is None:
            await message.answer(NOT_LINKED)
            return
        thread = await rider_threads.active_for_rider(rider_id, touch=False)
        if thread is None or thread.order_number is None:
            await message.answer(NO_JOB)
            return
        summary = await _order_summary(thread.order_number)
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: /job failed")
        await message.answer(TROUBLE)
        return
    from utils_common.tz_utils import fmt_uk_time

    lines = [f"<b>Current job: {escape(thread.order_number)}</b>"]
    if summary:
        if summary.get("pickup_time"):
            lines.append(f"⏰ Pickup: {escape(fmt_uk_time(summary['pickup_time']))}")
        lines.append(f"🏠 {escape(summary.get('rest_name'))}, {escape(summary.get('rest_address'))}")
        lines.append(f"📍 Drop-off: {escape(summary.get('customer_address'))}")
    if thread.channel != "telegram":
        lines.append(escape(wrong_channel_text(thread.order_number, thread.channel).replace("*", "")))
    await message.answer("\n".join(lines))


async def _order_summary(order_number: str) -> dict | None:
    from config import client_ordelo

    resp = await asyncio.to_thread(
        lambda: client_ordelo.table("delivery_summary")
        .select("order_number, pickup_time, rest_name, rest_address, customer_address")
        .eq("order_number", order_number)
        .limit(1)
        .execute()
    )
    return (resp.data or [None])[0]


# ---- text -> the rider agent ---------------------------------------------------------------------------------------
async def on_text(message: Message, tgram_settings: TgramBotSettings):
    if message.chat.type != "private":
        return
    try:
        rider_id = await _rider_id(message.from_user.id)
        thread = await rider_threads.active_for_rider(rider_id) if rider_id else None
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: text lookup failed for {message.from_user.id}")
        await message.answer(TROUBLE)
        return
    if rider_id is None:
        await message.answer(NOT_LINKED)
        return
    if thread is None:
        await message.answer("No active job. Use /job to check, or /help.")
        return
    if thread.channel != "telegram":
        await message.answer(wa_to_html(wrong_channel_text(thread.order_number, thread.channel)))
        return
    try:
        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    except Exception:
        pass
    from ordelo.agents.agent_runner import run_rider_agent

    spawn(
        run_rider_agent(thread, human_msg=message.text,
                        state_update_dict={"latest_wa_msg_id": tg_ref(message.chat.id, message.message_id)}),
        f"agent turn for {thread.thread_id}",
    )


def build_jobs_router() -> Router:
    """A NEW Router each call. Mounted by rider/router.py before its own text fallback."""
    router = Router(name="rider_jobs")
    router.callback_query.register(on_offer_tap, RiderOffer.filter())
    router.callback_query.register(on_job_action, RiderJobAction.filter())
    router.message.register(cmd_job, Command("job"))
    router.message.register(on_text, F.text & ~F.text.startswith("/"))
    return router
