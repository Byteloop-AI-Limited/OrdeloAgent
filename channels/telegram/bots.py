"""
Telegram bot registry for OrdeloAgent.
    . One TelegramBot (settings + Bot + Dispatcher) per configured bot_key
    . Fresh Dispatcher and router tree per bot (never shared, never module-level)
    . Built in the FastAPI lifespan; sessions closed on shutdown
    . Never sets or deletes a webhook (webhook registration is an explicit operator step)
  Classes/Functions:
    . TelegramBot
    . build_rest_admin_dispatcher
    . build_registry
    . default_registry
    . find_by_slug
    . close_registry
"""

from dataclasses import dataclass
from typing import Callable, Iterable

from aiogram import Bot, Dispatcher
from loguru import logger

from config.tgram_setting import REST_ADMIN_BOT_KEY, TgramBotSettings

from .errors import register_error_handlers
from .rest_admin.router import build_router as build_rest_admin_router


@dataclass(frozen=True)
class TelegramBot:
    settings: TgramBotSettings
    bot: Bot
    dp: Dispatcher

    @property
    def key(self) -> str:
        return self.settings.bot_key


def build_rest_admin_dispatcher(settings: TgramBotSettings) -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(build_rest_admin_router())
    register_error_handlers(dp)
    dp["tgram_settings"] = settings  # injected into handlers that declare `tgram_settings`
    return dp


DISPATCHER_FACTORIES: dict[str, Callable[[TgramBotSettings], Dispatcher]] = {
    REST_ADMIN_BOT_KEY: build_rest_admin_dispatcher,
    # "rider": build_rider_dispatcher,  # later phase
}


def build_registry(entries: Iterable[tuple[TgramBotSettings, Bot]]) -> dict[str, TelegramBot]:
    registry: dict[str, TelegramBot] = {}
    for settings, bot in entries:
        registry[settings.bot_key] = TelegramBot(
            settings=settings, bot=bot, dp=DISPATCHER_FACTORIES[settings.bot_key](settings)
        )
    logger.info(f"telegram: registry built for {sorted(registry)}")
    return registry


def default_registry() -> dict[str, TelegramBot]:
    from config import rest_admin_bot, tgram_rest_admin_settings

    return build_registry([(tgram_rest_admin_settings, rest_admin_bot)])


def find_by_slug(registry: dict[str, TelegramBot], slug: str) -> TelegramBot | None:
    return next((b for b in registry.values() if b.settings.path_slug == slug), None)


async def close_registry(registry: dict[str, TelegramBot]) -> None:
    for tg in registry.values():
        await tg.bot.session.close()  # never delete/set the webhook here
