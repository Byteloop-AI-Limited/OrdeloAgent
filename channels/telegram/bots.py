"""
Telegram bot registry for OrdeloAgent.
    . One TelegramBot (settings + Bot + Dispatcher) per configured bot_key
    . Fresh Dispatcher and router tree per bot (never shared, never module-level)
    . Built in the FastAPI lifespan; sessions closed on shutdown
    . Each rest_admin bot also owns its OrderCards (order alerts; channels/telegram/rest_admin/order_cards), exposed as
      TelegramBot.cards for the order-alerts route and injected into handlers as `order_cards`
    . Each Dispatcher gets the InboxMiddleware (durable at-most-once handling, channels/telegram/inbox.py)
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
from .inbox import InboxMiddleware
from .rest_admin.order_cards import OrderCards
from .rest_admin.router import build_router as build_rest_admin_router


@dataclass(frozen=True)
class TelegramBot:
    settings: TgramBotSettings
    bot: Bot
    dp: Dispatcher
    cards: OrderCards | None = None  # rest_admin only

    @property
    def key(self) -> str:
        return self.settings.bot_key


def build_rest_admin_dispatcher(settings: TgramBotSettings, cards: OrderCards | None = None) -> Dispatcher:
    dp = Dispatcher()
    dp.update.outer_middleware(InboxMiddleware(settings.bot_key))  # at-most-once per update_id (D21)
    dp.include_router(build_rest_admin_router())
    register_error_handlers(dp)
    dp["tgram_settings"] = settings  # injected into handlers that declare `tgram_settings`
    dp["order_cards"] = cards  # injected into handlers that declare `order_cards`
    return dp


DISPATCHER_FACTORIES: dict[str, Callable[..., Dispatcher]] = {
    REST_ADMIN_BOT_KEY: build_rest_admin_dispatcher,
    # "rider": build_rider_dispatcher,  # later phase
}


def build_registry(entries: Iterable[tuple[TgramBotSettings, Bot]]) -> dict[str, TelegramBot]:
    registry: dict[str, TelegramBot] = {}
    for settings, bot in entries:
        cards = OrderCards(bot, settings.bot_key) if settings.bot_key == REST_ADMIN_BOT_KEY else None
        factory = DISPATCHER_FACTORIES[settings.bot_key]
        dp = factory(settings, cards) if cards is not None else factory(settings)
        registry[settings.bot_key] = TelegramBot(settings=settings, bot=bot, dp=dp, cards=cards)
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
