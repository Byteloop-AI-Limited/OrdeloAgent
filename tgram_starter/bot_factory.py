"""Builds the Bot + Dispatcher once. Shared by webhook (app.py) and polling (polling.py)."""
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import Settings
from .handlers import basic, interactive, onboarding


def build_bot(settings: Settings) -> Bot:
    return Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def build_dispatcher(settings: Settings) -> Dispatcher:
    dp = Dispatcher()
    dp["settings"] = settings  # injected into any handler that declares a `settings` argument
    # Order matters: specific handlers first, generic text echo last.
    dp.include_router(onboarding.router)
    dp.include_router(interactive.router)
    dp.include_router(basic.router)
    return dp
