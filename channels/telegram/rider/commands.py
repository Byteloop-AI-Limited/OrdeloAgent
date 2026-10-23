"""Rider bot command menu (published by notebooks/telegram/tgram_setup_bot.py with bot_key 'rider').

R1: /start, /help, /whoami. R4: /job. R5: /shift, /off, /on. Keep this list and the routers in step.
The default menu includes all commands. A rider's private chat gets an inflight override without /off and /on;
deleting that override restores the default. Menu visibility is not authorisation: handlers and pause RPCs check
delivery_inflight (ADR 0011 two-bot section).
"""

import asyncio

from aiogram.types import BotCommand, BotCommandScopeChat
from loguru import logger

RIDER_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Link your rider account (share your phone number)"),
    BotCommand(command="job", description="Your current job"),
    BotCommand(command="shift", description="Are you getting job offers right now?"),
    BotCommand(command="off", description="Take a break from job offers for a while"),
    BotCommand(command="on", description="Back on: get job offers again"),
    BotCommand(command="help", description="What this bot can do"),
    BotCommand(command="whoami", description="Show your Telegram ids and rider link"),
]

HELP_TEXT = "<b>Byteloop riders</b>\n" + "\n".join(f"/{c.command} - {c.description}" for c in RIDER_COMMANDS)
INFLIGHT_COMMANDS = [command for command in RIDER_COMMANDS if command.command not in {"off", "on"}]
INFLIGHT_HELP_TEXT = "<b>Byteloop riders</b>\n" + "\n".join(
    f"/{command.command} - {command.description}" for command in INFLIGHT_COMMANDS
)


async def set_inflight_menu(bot, chat_id: int, inflight: bool) -> None:
    """Override one private chat during a job; otherwise inherit the published default menu."""
    scope = BotCommandScopeChat(chat_id=chat_id)
    try:
        if inflight:
            await bot.set_my_commands(INFLIGHT_COMMANDS, scope=scope)
        else:
            await bot.delete_my_commands(scope=scope)
    except Exception:
        logger.exception(f"telegram[rider]: could not update command menu for chat {chat_id}")


async def sync_rider_menu(rider_id: str) -> None:
    """Reconcile the menu after a delivery_inflight transition. Menu failures never undo delivery work."""
    try:
        from config import client_ordelo_service, rider_bot
        from ordelo.rider_shift import inflight_order

        if rider_bot is None:
            return
        resp = await asyncio.to_thread(
            lambda: client_ordelo_service.table("rider_master")
            .select("tcid").eq("rider_id", rider_id).limit(1).execute()
        )
        rows = resp.data or []
        if rows and rows[0].get("tcid") is not None:
            await set_inflight_menu(rider_bot, int(rows[0]["tcid"]), await inflight_order(rider_id) is not None)
    except Exception:
        logger.exception(f"telegram[rider]: could not sync command menu for rider {rider_id}")
