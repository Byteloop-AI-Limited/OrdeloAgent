"""
The two pause messages job_pause_sweep() asks for (ADR 0013, D51): "your break ends soon" and "you're back on".
    . Riders (audience 'rider'): through RiderMessenger.for_rider(principal), i.e. the rider's channel (Telegram riders on the
      rider bot; a WhatsApp rider paused by an operator on WhatsApp). Text in WhatsApp style, converted by the adapter.
    . Restaurant admins (audience 'rest_admin'): on the restaurant bot, only in that admin's own chats for that restaurant
      (channels.telegram.admin_pauses.chats -> t_admin_pause_chats()). An admin with no Telegram chat gets nothing (the
      pause was set by an operator); WhatsApp is not used for admin pause messages.
    . Never raises: one failed send is logged and the others still go (the sweep has already marked them on its 2xx).
    . Called by: watomation/routers/pause_hooks.py (POST /pause-hooks/sweep, from job_pause_sweep() in
      ordelo_datamodels/availability/job_pause_sweep.sql)
  Classes/Functions:
    . ENDING_SOON, ENDED
    . rider_text, admin_text (pure)
    . tell_rider, tell_admin
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any, Literal

from loguru import logger

from .pauses import ends_text

ENDING_SOON = "ending_soon"
ENDED = "ended"
Kind = Literal["ending_soon", "ended"]


def rider_text(kind: Kind, ends_at: datetime, *, telegram: bool) -> str:
    if kind == ENDING_SOON:
        text = f"⏰ Your break ends at *{ends_text(ends_at)}*. Job offers start again after that."
        if telegram:
            text += "\nSend /off to make it longer, or /on to come back now."
        return text
    return "✅ Your break is over. You're back on and will get job offers again."


def admin_text(kind: Kind, rest_name: str, ends_at: datetime) -> str:
    name = f"<b>{escape(rest_name, quote=False)}</b>"
    if kind == ENDING_SOON:
        return (f"⏰ Order alerts for {name} start again at {escape(ends_text(ends_at), quote=False)}.\n"
                "Send /off to pause for longer, or /on to turn them on now.")
    return f"🔔 Order alerts for {name} are back on."


async def tell_rider(rider_id: str, kind: Kind, ends_at: datetime) -> bool:
    try:
        from .rider_messaging import for_rider

        messenger = await for_rider(rider_id)
        await messenger.say(rider_text(kind, ends_at, telegram=messenger.channel == "telegram"))
        return True
    except Exception:
        logger.exception(f"pause notice {kind} to rider {rider_id} failed")
        return False


async def tell_admin(bot: Any, bot_key: str, phone: str, rest_ref: str, kind: Kind, ends_at: datetime) -> int:
    """Send to each of the admin's chats for that restaurant; returns how many were sent."""
    if bot is None:
        logger.warning(f"pause notice {kind} to admin {phone} ({rest_ref}): restaurant bot not configured")
        return 0
    try:
        from channels.telegram import admin_pauses

        targets = await admin_pauses.chats(bot_key, phone, rest_ref)
    except Exception:
        logger.exception(f"pause notice {kind} to admin {phone} ({rest_ref}): chat lookup failed")
        return 0
    sent = 0
    for tcid, rest_name in targets:
        try:
            await bot.send_message(tcid, admin_text(kind, rest_name, ends_at))
            sent += 1
        except Exception:
            logger.exception(f"pause notice {kind} to admin chat {tcid} ({rest_ref}) failed")
    return sent
