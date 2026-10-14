"""/app: opens the Mini App from a button. The page itself is served by miniapp/router.py."""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from ..config import Settings

router = Router(name="miniapp")


def miniapp_ready(settings: Settings) -> bool:
    return settings.miniapp_url.startswith("https://")  # Telegram refuses to open http:// web apps


@router.message(Command("app"))
async def cmd_app(message: Message, settings: Settings):
    if not miniapp_ready(settings):
        await message.answer("Mini app is not configured. Set TGRAM_WEBHOOK_BASE_URL (or TGRAM_MINIAPP_URL) to a public https:// URL.")
        return
    # A WebApp button in an INLINE keyboard opens the page and signs initData for the tapping user.
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🍽 Open Demo Kitchen", web_app=WebAppInfo(url=settings.miniapp_url))]])
    await message.answer("Tap to open the mini app inside Telegram:", reply_markup=kb)
