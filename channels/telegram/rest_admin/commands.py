"""Restaurant-admin bot command menu (published by notebooks/telegram/tgram_setup_bot.py)."""

from aiogram.types import BotCommand

REST_ADMIN_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Link this chat: share your phone number"),
    BotCommand(command="channels", description="Choose Telegram, WhatsApp or both for alerts"),
    BotCommand(command="manage", description="Open your restaurant dashboard (orders, reports)"),
    BotCommand(command="off", description="Pause new order alerts here for a while"),
    BotCommand(command="on", description="Turn order alerts back on"),
    BotCommand(command="help", description="What this bot can do"),
    BotCommand(command="whoami", description="Show your Telegram ids and link status"),
]

HELP_TEXT = "<b>Ordelo restaurant bot</b>\n" + "\n".join(
    f"/{c.command} - {c.description}" for c in REST_ADMIN_COMMANDS
)
