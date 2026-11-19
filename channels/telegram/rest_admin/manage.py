"""Restaurant bot, dashboard link: /manage sends one-time links to the restaurant-admin dashboard (restaurant-frontend).

    /manage -> dashboard_links.issue("rest_admin", Actor(tuid=from_user.id))
               (RPCs portal_access + rest_admin_dashboard_mint per restaurant, admin_dashboard/auth_sessions.sql:
                membership re-checked in the transaction that stores the link)
            -> one URL button per restaurant: "Manage <restaurant>"
            -> overwatch members also get a "System dashboard" button (callback 'sa1:go', handled by sysadmin.py, which
               mints the sys-admin link only when tapped and re-checks overwatch then)
It is the Telegram twin of WhatsApp `/login` (watomation/on_message_wa_handler.py handle_login_wa_msg); both mint
auth_sessions rows (role rest_admin, scope_ref = rest_ref, principal = the verified phone): 30 minutes, works once.
A restaurant on WhatsApp-only alerts still gets a link: /manage needs a linked Telegram account, not Telegram alerts.
The restaurant links never depend on the sys-admin check: if that lookup fails the restaurant buttons are still sent.

Private chats only: the link is a login credential. The URL goes in an inline button with link previews off. The frontend
opens a non-consuming page and activates with a POST (lib/dashboard-activation.ts), so a preview cannot use the link up,
but previews stay off anyway. If Telegram refuses the button URL (a plain http:// or localhost dashboard URL in local
testing), the links are sent as text, still with previews off. URLs are never logged.
"""

from __future__ import annotations

from html import escape as _html_escape

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Message
from loguru import logger

from config.tgram_setting import TgramBotSettings
from ordelo.dashboard_links import Actor, PortalAccess, access, issue

from ..callbacks import SysAdminLink
from .menu import sync_admin_menu
from .order_cards.model import TROUBLE

PRIVATE_ONLY = "Please message me in a private chat."
NOT_LINKED = "This chat isn't linked to a restaurant yet. Send /start to link it, then /manage."
NOT_ON_ROSTER = "This number isn't on any restaurant's admin list any more. Ask your Ordelo contact if that's wrong."
OPS_ONLY = "You don't admin a restaurant. Tap <b>System dashboard</b> below, or send /sysadmin."
INTRO = (
    "Manage your restaurant on the Ordelo dashboard.\n"
    "<i>The link expires in 30 minutes and works once. Send /manage again for a new one.</i>"
)
SYSTEM_BUTTON = "System dashboard"
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def escape(text) -> str:
    return _html_escape(str(text or ""), quote=False)


def manage_keyboard(links: list[tuple[str, str]], sys_admin: bool = False) -> InlineKeyboardMarkup:
    """One URL button per (label, link); overwatch members get a System dashboard button underneath."""
    rows = [[InlineKeyboardButton(text=label, url=url)] for label, url in links]
    if sys_admin:
        rows.append([InlineKeyboardButton(text=SYSTEM_BUTTON, callback_data=SysAdminLink().pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def links_as_text(links: list[tuple[str, str]]) -> str:
    return INTRO + "\n\n" + "\n\n".join(f"<b>{escape(label)}</b>\n{escape(url)}" for label, url in links)


async def cmd_manage(message: Message, tgram_settings: TgramBotSettings):
    if message.chat.type != "private":
        await message.answer(PRIVATE_ONLY)
        return
    key, tuid = tgram_settings.bot_key, message.from_user.id
    actor = Actor(tuid=tuid)
    try:
        out = await issue("rest_admin", actor)
    except Exception:
        logger.warning(f"telegram[{key}]: /manage could not issue links for user {tuid}")
        await message.answer(TROUBLE)
        return
    acc: PortalAccess | None
    try:  # independent of the restaurant links: a failure here only hides the System dashboard button
        acc = await access(actor)
    except Exception:
        logger.warning(f"telegram[{key}]: /manage sys-admin lookup failed for user {tuid}")
        acc = None
    sys_admin = bool(acc and acc.sys_admin)
    if acc is not None:
        await sync_admin_menu(message.bot, message.chat.id, acc)
    if not out.ok:
        if sys_admin:
            await message.answer(OPS_ONLY, reply_markup=manage_keyboard([], sys_admin=True))
        else:
            await message.answer(NOT_LINKED if out.result == "not_linked" else NOT_ON_ROSTER)
        return
    links = [(link.label, link.url) for link in out.links]
    logger.info(f"telegram[{key}]: /manage sent {len(links)} dashboard link(s) to user {tuid}: "
                + ", ".join(link.rest_ref or "?" for link in out.links) + (" (+system)" if sys_admin else ""))
    try:
        await message.answer(INTRO, reply_markup=manage_keyboard(links, sys_admin), link_preview_options=NO_PREVIEW)
    except TelegramBadRequest as e:  # e.g. BUTTON_URL_INVALID for an http:// or localhost dashboard URL
        logger.warning(f"telegram[{key}]: /manage button refused ({e.message}); sending links as text")
        await message.answer(links_as_text(links), link_preview_options=NO_PREVIEW,
                             reply_markup=manage_keyboard([], sys_admin=True) if sys_admin else None)


def build_manage_router() -> Router:
    """A NEW Router each call. Included by rest_admin/router.py before its text fallback."""
    router = Router(name="rest_admin_manage")
    router.message.register(cmd_manage, Command("manage"))
    return router
