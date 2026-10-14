"""Builds the Bot + Dispatcher once. Used by app.py and the notebooks."""
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import ExceptionTypeFilter
from aiogram.types import ErrorEvent

from .config import Settings
from .handlers import basic, interactive, miniapp, onboarding

log = logging.getLogger(__name__)


def build_bot(settings: Settings) -> Bot:
    return Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


_dp: Dispatcher | None = None


def build_dispatcher(settings: Settings) -> Dispatcher:
    # The handler routers are module-level and aiogram lets a router join only one Dispatcher,
    # so build it once and reuse it (re-running a notebook cell would otherwise raise RuntimeError).
    global _dp
    if _dp is None:
        _dp = Dispatcher()
        # Order matters: specific handlers first, generic text echo last.
        _dp.include_router(onboarding.router)
        _dp.include_router(interactive.router)
        _dp.include_router(miniapp.router)
        _dp.include_router(basic.router)
        _dp.errors.register(_ignore_stale_callback, ExceptionTypeFilter(TelegramBadRequest))
    _dp["settings"] = settings  # injected into any handler that declares a `settings` argument
    return _dp


async def _ignore_stale_callback(event: ErrorEvent):
    # A button tap must be answered within ~15s. A late or redelivered tap can't be answered any more,
    # so drop it instead of failing the update (which would make Telegram retry it forever).
    if "query is too old" not in event.exception.message:
        raise event.exception
    log.warning("Ignoring stale callback query (update %s)", event.update.update_id)
