"""Private /my_jobs and /portal entry to the rider portal (jobs, earnings, payouts); no agent or inbox work.

ordelo.dashboard_links.issue("rider") authorizes the Telegram actor (rider_dashboard_mint) and issues one credential.
The link opens a non-consuming page; the browser automatically POSTs to activate it. /portal is an alias of /my_jobs.
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Message
from loguru import logger

from ordelo.dashboard_links import Actor, issue

from .. import rider_links
from ..keyboards import contact_request_kb


async def cmd_my_jobs(message: Message):
    if message.chat.type != "private":
        await message.answer("Please message me in a private chat.")
        return
    if not message.from_user:
        return
    try:
        out = await issue("rider", Actor(tuid=message.from_user.id))
        if not out.ok:
            profile = await rider_links.profile(message.from_user.id)
            if profile.is_linked and not profile.phone_verified:
                await message.answer(
                    "To use the rider portal, share your own matching phone number below, then send /portal.",
                    reply_markup=contact_request_kb(),
                )
            else:
                await message.answer("Send /start to link your rider account, then /portal.")
            return
        await message.answer(
            "Your rider portal: jobs, earnings and payouts.\n"
            "This link expires in 30 minutes and works once. Send /portal (or /my_jobs) for a new link.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="Open my jobs", url=out.links[0].url),
            ]]),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    except Exception:
        # Exception text can include the rejected URL; never log it or the credential.
        logger.warning("telegram[rider]: /portal could not issue/send dashboard access")
        await message.answer("Sorry, something went wrong. Please try /portal again shortly.")


def build_dashboard_router() -> Router:
    router = Router(name="rider_dashboard")
    router.message.register(cmd_my_jobs, Command("my_jobs", "portal"))
    return router
