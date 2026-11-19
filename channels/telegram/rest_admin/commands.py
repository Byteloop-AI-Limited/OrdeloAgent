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

# ---- capability menus (channels/telegram/rest_admin/menu.py) --------------------------------------------------------
# The published default above never lists /sysadmin. An overwatch member's private chat gets a per-chat override
# (BotCommandScopeChat): admins who are also overwatch see the default plus /sysadmin; overwatch members who admin no
# restaurant see only what they can use. Menus are guidance, not authority: every handler re-checks (ADR 0013 Am. 2).
SYSADMIN_COMMAND = BotCommand(command="sysadmin", description="Open the Ordelo system dashboard (operations)")
ADMIN_AND_OPS_COMMANDS: list[BotCommand] = [*REST_ADMIN_COMMANDS[:3], SYSADMIN_COMMAND, *REST_ADMIN_COMMANDS[3:]]
OPS_ONLY_COMMANDS: list[BotCommand] = [
    REST_ADMIN_COMMANDS[0],
    SYSADMIN_COMMAND,
    *(c for c in REST_ADMIN_COMMANDS if c.command in ("help", "whoami")),
]
