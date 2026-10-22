"""
Telegram bot registry for OrdeloAgent.
    . One TelegramBot (settings + Bot + Dispatcher) per configured bot_key
    . Fresh Dispatcher and router tree per bot (never shared, never module-level)
    . Built in the FastAPI lifespan; sessions closed on shutdown
    . Each rest_admin bot also owns its OrderCards (order alerts; channels/telegram/rest_admin/order_cards), exposed as
      TelegramBot.cards for the order-alerts route and injected into handlers as `order_cards`, and its Receipts
      (kitchen receipts; channels/telegram/rest_admin/receipts), exposed as TelegramBot.receipts and injected as `receipts`
    . Each Dispatcher gets the InboxMiddleware (durable at-most-once handling, channels/telegram/inbox.py)
    . Never sets or deletes a webhook (webhook registration is an explicit operator step)
    . Removable scratchpad router is mounted before the restaurant router's text fallback
    . The rider bot (bot_key 'rider', channels/telegram/rider) is registered only when configured (D54): config.rider_bot
      is None without a tgram_rider_bot_token, and default_registry() then builds the restaurant-admin bot alone
  Classes/Functions:
    . TelegramBot
    . build_rest_admin_dispatcher
    . build_rider_dispatcher
    . build_registry
    . default_registry
    . find_by_slug
    . close_registry
"""

from dataclasses import dataclass
from typing import Callable, Iterable

from aiogram import Bot, Dispatcher
from loguru import logger

from config.tgram_setting import REST_ADMIN_BOT_KEY, RIDER_BOT_KEY, TgramBotSettings

from .errors import register_error_handlers
from .inbox import InboxMiddleware
from .rest_admin.order_cards import OrderCards
from .rest_admin.receipts import Receipts
from .rest_admin.router import build_router as build_rest_admin_router
from .rest_admin.scratchpad import build_scratchpad_router
from .rider.router import build_router as build_rider_router


@dataclass(frozen=True)
class TelegramBot:
    settings: TgramBotSettings
    bot: Bot
    dp: Dispatcher
    cards: OrderCards | None = None  # rest_admin only
    receipts: Receipts | None = None  # rest_admin only

    @property
    def key(self) -> str:
        return self.settings.bot_key


def build_rest_admin_dispatcher(
    settings: TgramBotSettings, cards: OrderCards | None = None, receipts: Receipts | None = None
) -> Dispatcher:
    dp = Dispatcher()
    dp.update.outer_middleware(InboxMiddleware(settings.bot_key))  # at-most-once per update_id (D21)
    dp.include_router(build_scratchpad_router())  # unmount /scratchpad: remove this line (and its import)
    dp.include_router(build_rest_admin_router())
    register_error_handlers(dp)
    dp["tgram_settings"] = settings  # injected into handlers that declare `tgram_settings`
    dp["order_cards"] = cards  # injected into handlers that declare `order_cards`
    dp["receipts"] = receipts  # injected into handlers that declare `receipts`
    return dp


def build_rider_dispatcher(settings: TgramBotSettings) -> Dispatcher:
    """The rider bot: its own Dispatcher, inbox and router tree; never shares routers with the restaurant bot."""
    dp = Dispatcher()
    dp.update.outer_middleware(InboxMiddleware(settings.bot_key))  # at-most-once per update_id (D21)
    dp.include_router(build_rider_router())
    register_error_handlers(dp)
    dp["tgram_settings"] = settings
    return dp


DISPATCHER_FACTORIES: dict[str, Callable[..., Dispatcher]] = {
    REST_ADMIN_BOT_KEY: build_rest_admin_dispatcher,
    RIDER_BOT_KEY: build_rider_dispatcher,
}


def build_registry(entries: Iterable[tuple[TgramBotSettings, Bot]]) -> dict[str, TelegramBot]:
    registry: dict[str, TelegramBot] = {}
    for settings, bot in entries:
        is_rest_admin = settings.bot_key == REST_ADMIN_BOT_KEY
        cards = OrderCards(bot, settings.bot_key) if is_rest_admin else None
        receipts = Receipts(bot, settings.bot_key) if is_rest_admin else None
        factory = DISPATCHER_FACTORIES[settings.bot_key]
        dp = factory(settings, cards, receipts) if is_rest_admin else factory(settings)
        registry[settings.bot_key] = TelegramBot(settings=settings, bot=bot, dp=dp, cards=cards, receipts=receipts)
    logger.info(f"telegram: registry built for {sorted(registry)}")
    return registry


def default_registry() -> dict[str, TelegramBot]:
    from config import rest_admin_bot, rider_bot, tgram_rest_admin_settings, tgram_rider_settings

    entries = [(tgram_rest_admin_settings, rest_admin_bot)]
    if tgram_rider_settings is not None and rider_bot is not None:
        entries.append((tgram_rider_settings, rider_bot))
    return build_registry(entries)


def find_by_slug(registry: dict[str, TelegramBot], slug: str) -> TelegramBot | None:
    return next((b for b in registry.values() if b.settings.path_slug == slug), None)


async def close_registry(registry: dict[str, TelegramBot]) -> None:
    for tg in registry.values():
        await tg.bot.session.close()  # never delete/set the webhook here
