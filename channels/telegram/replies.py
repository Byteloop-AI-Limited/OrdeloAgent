"""
Safe callback-query answers for Telegram handlers.
    . answer_quietly(query, text, show_alert): answers a button tap and NEVER raises or waits long
    . Why: answering the tap (clearing the spinner / showing a toast) is a courtesy. If the Bot API call hangs or
      fails (a dead pooled connection, an expired query) it must not stop the real work of the handler, and
      the webhook handler has only 25 s in total. Handlers start it as a task and run their real work beside it.
  Classes/Functions:
    . answer_quietly
"""

import asyncio

from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery
from loguru import logger

CALLBACK_ANSWER_TIMEOUT_SECS = 3


async def answer_quietly(query: CallbackQuery, text: str | None = None, show_alert: bool = False) -> None:
    try:
        await asyncio.wait_for(query.answer(text, show_alert=show_alert), timeout=CALLBACK_ANSWER_TIMEOUT_SECS)
    except (TelegramAPIError, asyncio.TimeoutError) as e:
        logger.warning(f"telegram: could not answer callback query ({type(e).__name__}): {e}")
