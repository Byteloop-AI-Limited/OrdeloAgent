"""Rider bot, a shared location (phase R5, D50): the answer to a location request, through the same WaLocation module as WhatsApp.

    the agent (or WaLocation's direct prompt) sends "Please share your current location" with the one-tap
    [📍 Share current location] reply keyboard (TelegramRiderMessenger.request_location); the prompt's MsgRef is stored in
    wa_location_request.wa_request_message_id
    the rider taps it -> a message with .location (no live_period, no venue)
      -> WaLocation.receive_current_location(receipt with source 'telegram_current', ids 'tg:<chat>:<message>')
         correlated -> the requesters' callbacks are sent; the rider agent acknowledges on the job's thread (as on WhatsApp)
         nothing pending -> "No location was requested right now" (and the reply keyboard is removed)
    a live location or a picked place (venue) is refused with a pointer to the button (Telegram live location is out of
    scope, D50; a picked place is not where the rider is)
Authorisation: from_user.id -> rider_master.tuid -> rider_id; WaLocation then accepts the share only for that rider's
pending request whose job is still their inflight job. The work runs in the background (callbacks can take seconds; the
webhook has 25 s).
"""

from __future__ import annotations

from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.types import Message, ReplyKeyboardRemove
from loguru import logger

from config.tgram_setting import TgramBotSettings
from ordelo.agents import rider_threads
from ordelo.rider_messaging import tg_ref
from ordelo_datamodels.wa_location_pymodels import WhatsAppLocationReceipt

from .. import rider_links
from ..keyboards import location_request_kb
from . import jobs

NOT_LINKED = "Please send /start first to link your rider account."
USE_THE_BUTTON = "Please use the <b>📍 Share current location</b> button (not a live location or a picked place)."
NOTHING_PENDING = "Thanks. No location was requested right now."
TROUBLE = "Sorry, something went wrong on our side. Please try again in a minute."
ACK_SYSTEM_MSG = "Rider shared their current location and it has been sent to the requester. Acknowledge briefly in one line."


def _observed_at(message: Message) -> datetime:
    d = message.date
    if isinstance(d, datetime):
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


async def on_location(message: Message, tgram_settings: TgramBotSettings):
    if message.chat.type != "private":
        return
    loc = message.location
    if message.venue is not None or getattr(loc, "live_period", None):
        await message.answer(USE_THE_BUTTON, reply_markup=location_request_kb())
        return
    try:
        prof = await rider_links.profile(message.from_user.id)
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: location lookup failed for user {message.from_user.id}")
        await message.answer(TROUBLE)
        return
    if not prof.is_linked:
        await message.answer(NOT_LINKED)
        return
    reply = message.reply_to_message
    receipt = WhatsAppLocationReceipt(
        rider_id=prof.rider_id,
        latitude=loc.latitude,
        longitude=loc.longitude,
        observed_at=_observed_at(message),
        inbound_message_id=tg_ref(message.chat.id, message.message_id),
        reply_to_message_id=tg_ref(message.chat.id, reply.message_id) if reply is not None else None,
        source="telegram_current",
    )
    jobs.spawn(_receive(message, receipt), f"location from rider {prof.rider_id}")


async def _receive(message: Message, receipt: WhatsAppLocationReceipt) -> None:
    from ordelo.wa_location import WaLocation

    try:
        correlated = await WaLocation().receive_current_location(receipt)
    except Exception:
        logger.exception(f"telegram[rider]: WaLocation failed for rider {receipt.rider_id}")
        await message.answer(TROUBLE, reply_markup=ReplyKeyboardRemove())
        return
    if not correlated:
        await message.answer(NOTHING_PENDING, reply_markup=ReplyKeyboardRemove())
        return
    thread = await rider_threads.active_for_rider(receipt.rider_id)
    if thread is not None and thread.channel == "telegram":
        from ordelo.agents.agent_runner import run_rider_agent_w_custom_msg

        await run_rider_agent_w_custom_msg(recipient=receipt.rider_id, thread_id=thread.thread_id, system_msg=ACK_SYSTEM_MSG)


def build_location_router() -> Router:
    """A NEW Router each call. Mounted by rider/router.py."""
    router = Router(name="rider_location")
    router.message.register(on_location, F.location)
    return router
