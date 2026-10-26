"""Restaurant bot, dashboard link: /manage sends a one-time link to the restaurant-admin dashboard (restaurant-frontend).

    /manage -> admin_links.profile(from_user.id)                               (RPC t_admin_profile: phone + restaurants)
            -> per restaurant: mint_dashboard_session_for(phone, rest_ref)    (watomation/routers/rest_admin_auth_session.py)
            -> one URL button per restaurant: "Manage <restaurant>"
It is the Telegram twin of WhatsApp `/login` (watomation/on_message_wa_handler.py handle_login_wa_msg) and mints the same
auth_sessions rows (role rest_admin, scope_ref = rest_ref, wa_number = the admin's phone): 30 minutes, works once.
Authorisation: the sender's from_user.id (D14) -> linked admin record -> restaurants whose admins[] list holds that phone.
A restaurant on WhatsApp-only alerts still gets a link: /manage needs a linked Telegram account, not Telegram alerts.

Private chats only: the link is a login credential. The URL goes in an inline button with link previews off, because the
frontend activates the token on GET (app/rest-admin/activate/[token]/route.ts): a link preview fetched by Telegram's servers
would use it up before the admin taps it. If Telegram refuses the button URL (a plain http:// or localhost dashboard URL in
local testing), the links are sent as text, still with previews off.
"""

from __future__ import annotations

from html import escape as _html_escape

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Message
from loguru import logger

from config.tgram_setting import TgramBotSettings
from watomation.routers.rest_admin_auth_session import mint_dashboard_session_for

from .. import admin_links
from .order_cards.model import TROUBLE

PRIVATE_ONLY = "Please message me in a private chat."
NOT_LINKED = "This chat isn't linked to a restaurant yet. Send /start to link it, then /manage."
NOT_ON_ROSTER = "This number isn't on any restaurant's admin list any more. Ask your Ordelo contact if that's wrong."
INTRO = (
    "Manage your restaurant on the Ordelo dashboard.\n"
    "<i>The link expires in 30 minutes and works once. Send /manage again for a new one.</i>"
)
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def escape(text) -> str:
    return _html_escape(str(text or ""), quote=False)


def manage_keyboard(links: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """One URL button per (restaurant name, link)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=f"Manage {name}", url=url)] for name, url in links]
    )


def links_as_text(links: list[tuple[str, str]]) -> str:
    return INTRO + "\n\n" + "\n\n".join(f"<b>{escape(name)}</b>\n{escape(url)}" for name, url in links)


async def cmd_manage(message: Message, tgram_settings: TgramBotSettings):
    if message.chat.type != "private":
        await message.answer(PRIVATE_ONLY)
        return
    tuid = message.from_user.id
    try:
        prof = await admin_links.profile(tuid)
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: /manage profile lookup failed for user {tuid}")
        await message.answer(TROUBLE)
        return
    if prof.result == "not_on_roster":
        await message.answer(NOT_ON_ROSTER)
        return
    if not prof.is_admin or not prof.phone or not prof.restaurants:
        await message.answer(NOT_LINKED)
        return
    try:
        links = [(r.rest_name, await mint_dashboard_session_for(prof.phone, r.rest_ref)) for r in prof.restaurants]
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: /manage link mint failed for user {tuid}")
        await message.answer(TROUBLE)
        return
    logger.info(f"telegram[{tgram_settings.bot_key}]: /manage sent {len(links)} dashboard link(s) to user {tuid}: "
                + ", ".join(r.rest_ref for r in prof.restaurants))
    try:
        await message.answer(INTRO, reply_markup=manage_keyboard(links), link_preview_options=NO_PREVIEW)
    except TelegramBadRequest as e:  # e.g. BUTTON_URL_INVALID for an http:// or localhost dashboard URL
        logger.warning(f"telegram[{tgram_settings.bot_key}]: /manage button refused ({e.message}); sending links as text")
        await message.answer(links_as_text(links), link_preview_options=NO_PREVIEW)


def build_manage_router() -> Router:
    """A NEW Router each call. Included by rest_admin/router.py before its text fallback."""
    router = Router(name="rest_admin_manage")
    router.message.register(cmd_manage, Command("manage"))
    return router
