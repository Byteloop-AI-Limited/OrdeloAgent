"""Shared Dispatcher error handlers for every Ordelo Telegram bot."""

from aiogram import Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import ExceptionTypeFilter
from aiogram.types import ErrorEvent
from loguru import logger


async def ignore_stale_callback(event: ErrorEvent):
    # A button tap must be answered within ~15s; late/redelivered taps can't be answered any more,
    # so drop them instead of failing the update (which would make Telegram retry it forever).
    if "query is too old" not in event.exception.message:
        raise event.exception
    logger.warning(f"telegram: ignoring stale callback query (update {event.update.update_id})")


def register_error_handlers(dp: Dispatcher) -> None:
    dp.errors.register(ignore_stale_callback, ExceptionTypeFilter(TelegramBadRequest))
