"""TelegramIO: send, edit and delete order-card messages, mapping Telegram errors to a small vocabulary.

    . send   -> message_id | None      None = the chat can not receive it (bot blocked, kicked, chat gone) or
                                       the send failed; the caller skips that destination
    . edit   -> 'edited' | 'gone' | 'retry'
    . A View with a `rich` form is sent/edited as a rich message first. Only a definitive rejection (TelegramBadRequest:
      nothing was sent or changed) falls back to the HTML form; a timeout or network error never does, so a message that
      may already have been delivered is not sent twice.
    . delete -> 'deleted' | 'gone' | 'retry'
    . 'retry' means "leave the ledger row claimed": the sweep offers it again after 30 seconds
    . Error mapping (plans/archive/telegram-rest-admin-scaffold-plan-full-2026-10-15.md): "message is not modified" = edited;
      "message to edit/delete not found", "message can't be edited/deleted", "chat not found" and
      TelegramForbiddenError = gone; TelegramRetryAfter = sleep retry_after once, then retry once;
      anything else = retry.
  Classes/Functions:
    . TelegramIO
"""

import asyncio
from typing import Literal

from aiogram import Bot
from aiogram.types import ReplyParameters
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from loguru import logger

from .model import View

MAX_RETRY_AFTER_SECS = 30
_GONE_MARKERS = ("not found", "can't be edited", "can't be deleted", "message_id_invalid", "chat not found")


def _is_not_modified(e: TelegramBadRequest) -> bool:
    return "message is not modified" in str(e).lower()


def _is_gone(e: Exception) -> bool:
    if isinstance(e, TelegramForbiddenError):
        return True
    text = str(e).lower()
    return isinstance(e, TelegramBadRequest) and any(m in text for m in _GONE_MARKERS)


class TelegramIO:
    def __init__(self, bot: Bot):
        self._bot = bot

    async def _with_backoff(self, call):
        try:
            return await call()
        except TelegramRetryAfter as e:
            await asyncio.sleep(min(e.retry_after, MAX_RETRY_AFTER_SECS))
            return await call()

    async def send(self, tcid: int, view: View, reply_to: int | None = None) -> int | None:
        """Send one message. `reply_to` threads it under an earlier message in the same chat; a target the admin
        deleted by hand never fails the send (allow_sending_without_reply)."""
        extra = (
            {"reply_parameters": ReplyParameters(message_id=reply_to, allow_sending_without_reply=True)}
            if reply_to is not None
            else {}
        )
        if view.rich is not None:
            try:
                msg = await self._with_backoff(
                    lambda: self._bot.send_rich_message(tcid, rich_message=view.rich, **extra)
                )
                return msg.message_id
            except TelegramBadRequest as e:
                if _is_gone(e):
                    logger.info(f"telegram: rich send to chat {tcid} not possible: {e}")
                    return None
                logger.warning(f"telegram: rich message to chat {tcid} rejected, sending the HTML form instead: {e}")
            except (TelegramAPIError, OSError) as e:
                level = "info" if _is_gone(e) else "error"
                logger.log(level.upper(), f"telegram: rich send to chat {tcid} failed: {e}")
                return None
        try:
            msg = await self._with_backoff(
                lambda: self._bot.send_message(
                    tcid, view.text, parse_mode="HTML", reply_markup=view.keyboard, **extra
                )
            )
            return msg.message_id
        except (TelegramAPIError, OSError) as e:
            level = "info" if _is_gone(e) else "error"
            logger.log(level.upper(), f"telegram: order card send to chat {tcid} failed: {e}")
            return None

    async def _edit_rich(self, copy, view: View) -> Literal["edited", "gone", "retry"] | None:
        """Edit to the rich form. None = Telegram rejected it (nothing changed), so the caller tries the HTML form."""
        try:
            await self._with_backoff(
                lambda: self._bot.edit_message_text(
                    chat_id=copy.tcid, message_id=copy.message_id, rich_message=view.rich
                )
            )
            return "edited"
        except TelegramBadRequest as e:
            if _is_not_modified(e):
                return "edited"
            if _is_gone(e):
                return "gone"
            logger.warning(f"telegram: rich edit of {copy.tcid}/{copy.message_id} rejected, trying the HTML form: {e}")
            return None
        except TelegramForbiddenError:
            return "gone"
        except (TelegramAPIError, OSError) as e:
            logger.error(f"telegram: rich edit of {copy.tcid}/{copy.message_id} failed: {e}")
            return "retry"

    async def edit(self, copy, view: View) -> Literal["edited", "gone", "retry"]:
        if view.rich is not None:
            outcome = await self._edit_rich(copy, view)
            if outcome is not None:
                return outcome
        try:
            await self._with_backoff(
                lambda: self._bot.edit_message_text(
                    view.text, chat_id=copy.tcid, message_id=copy.message_id, parse_mode="HTML",
                    reply_markup=view.keyboard,
                )
            )
            return "edited"
        except TelegramBadRequest as e:
            if _is_not_modified(e):
                return "edited"
            if _is_gone(e):
                return "gone"
            logger.error(f"telegram: edit of {copy.tcid}/{copy.message_id} failed: {e}")
            return "retry"
        except TelegramForbiddenError:
            return "gone"
        except (TelegramAPIError, OSError) as e:
            logger.error(f"telegram: edit of {copy.tcid}/{copy.message_id} failed: {e}")
            return "retry"

    async def delete(self, copy) -> Literal["deleted", "gone", "retry"]:
        try:
            await self._with_backoff(lambda: self._bot.delete_message(copy.tcid, copy.message_id))
            return "deleted"
        except TelegramForbiddenError:
            return "gone"
        except TelegramBadRequest as e:
            if _is_gone(e):
                return "gone"
            logger.error(f"telegram: delete of {copy.tcid}/{copy.message_id} failed: {e}")
            return "retry"
        except (TelegramAPIError, OSError) as e:
            logger.error(f"telegram: delete of {copy.tcid}/{copy.message_id} failed: {e}")
            return "retry"
