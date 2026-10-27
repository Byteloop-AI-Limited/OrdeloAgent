"""Private /my_jobs entry to the existing rider dashboard; no agent or inbox work.

ordelo.rider_dashboard.issue_link authorizes the Telegram actor and issues one credential.
The link opens a non-consuming page; the browser automatically POSTs to activate it.
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Message
from loguru import logger

from ordelo.rider_dashboard import issue_link


async def cmd_my_jobs(message: Message):
    if message.chat.type != "private":
        await message.answer("Please message me in a private chat.")
        return
    if not message.from_user:
        return
    try:
        link = await issue_link(message.from_user.id)
        if link.result == "not_linked":
            await message.answer("Send /start to link your rider account, then /my_jobs.")
            return
        await message.answer(
            "Your jobs and earnings.\nThis link expires in 30 minutes and works once. Send /my_jobs for a new link.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="Open my jobs", url=link.url),
            ]]),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    except Exception:
        # Exception text can include the rejected URL; never log it or the credential.
        logger.warning("telegram[rider]: /my_jobs could not issue/send dashboard access")
        await message.answer("Sorry, something went wrong. Please try /my_jobs again shortly.")


def build_dashboard_router() -> Router:
    router = Router(name="rider_dashboard")
    router.message.register(cmd_my_jobs, Command("my_jobs"))
    return router
