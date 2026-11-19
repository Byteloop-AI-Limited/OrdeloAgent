"""Restaurant bot capability menu: which commands one private chat sees, and the matching /help text.

    sync_admin_menu(bot, chat_id, access) -> set or clear this chat's BotCommandScopeChat override
    help_text(access)                     -> /help built from the same list

Twin of the rider bot's set_inflight_menu (channels/telegram/rider/commands.py). The lists are in commands.py:
REST_ADMIN_COMMANDS (published default, no /sysadmin), ADMIN_AND_OPS_COMMANDS (admin + overwatch) and OPS_ONLY_COMMANDS
(overwatch, no restaurant). `access` is ordelo.dashboard_links.PortalAccess (restaurants + sys_admin from SQL).
The menu is guidance, never authority: /sysadmin and /manage re-check in SQL. Menu failures are logged and never fail
the command that triggered the sync. Reconciled on /start, a successful contact link, /help, /whoami, /manage and
/sysadmin (no cron), and for every linked chat by the rollout cell in notebooks/telegram/tgram_setup_bot.py.
"""

from __future__ import annotations

from aiogram.types import BotCommand, BotCommandScopeChat
from loguru import logger

from ordelo.dashboard_links import PortalAccess

from .commands import ADMIN_AND_OPS_COMMANDS, OPS_ONLY_COMMANDS, REST_ADMIN_COMMANDS


def commands_for(access: PortalAccess | None) -> list[BotCommand] | None:
    """The override for this chat, or None for the published default."""
    if access is None or access.result != "ok" or not access.sys_admin:
        return None
    return ADMIN_AND_OPS_COMMANDS if access.restaurants else OPS_ONLY_COMMANDS


async def sync_admin_menu(bot, chat_id: int, access: PortalAccess | None) -> None:
    scope = BotCommandScopeChat(chat_id=chat_id)
    try:
        commands = commands_for(access)
        if commands is None:
            await bot.delete_my_commands(scope=scope)
        else:
            await bot.set_my_commands(commands, scope=scope)
    except Exception:
        logger.exception(f"telegram[rest_admin]: could not update the command menu for chat {chat_id}")


def help_text(access: PortalAccess | None) -> str:
    commands = commands_for(access) or REST_ADMIN_COMMANDS
    return "<b>Ordelo restaurant bot</b>\n" + "\n".join(f"/{c.command} - {c.description}" for c in commands)
