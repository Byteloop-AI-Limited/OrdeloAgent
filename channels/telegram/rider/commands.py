"""Rider bot command menu (published by notebooks/telegram/tgram_setup_bot.py with bot_key 'rider').

Phase R1 ships /start, /help, /whoami. Later phases add /job (R4) and /shift, /off, /on (R5); keep this list and the
router in step. Menu visibility is not authorisation: every handler re-checks the actor (ADR 0011 two-bot section).
"""

from aiogram.types import BotCommand

RIDER_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Link your rider account (share your phone number)"),
    BotCommand(command="help", description="What this bot can do"),
    BotCommand(command="whoami", description="Show your Telegram ids and rider link"),
]

HELP_TEXT = "<b>Byteloop riders</b>\n" + "\n".join(f"/{c.command} - {c.description}" for c in RIDER_COMMANDS)
