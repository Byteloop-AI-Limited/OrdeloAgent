"""The only code that sends or edits order cards.

One card per restaurant admin chat, so every order has several copies. Real code: a table like
    tgram_order_card_messages(order_ref text, chat_id bigint, message_id bigint, primary key (order_ref, chat_id))
"""
import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup

from .render import render_buttons, render_text
from .state import load_order

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CardMessage:
    chat_id: int
    message_id: int


CARD_MESSAGES: dict[str, list[CardMessage]] = {}  # fake table: order_ref -> one copy per admin chat
# One edit at a time per order: two hooks firing together can't interleave, and each edit renders the
# state as it is when it runs, so the last edit always shows the latest state. Real code with several
# workers: a DB/Redis lock, or compare state.version before editing.
_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


async def send_order_card(bot: Bot, order_ref: str, chat_ids: list[int]) -> list[CardMessage]:
    """First send: one copy per admin chat. Stores the message ids so later refreshes can edit them."""
    state = await load_order(order_ref)
    if state is None:
        raise KeyError(order_ref)
    text, markup = render_text(state), render_buttons(state)
    async with _locks[order_ref]:
        for chat_id in chat_ids:
            msg = await bot.send_message(chat_id, text, reply_markup=markup)
            CARD_MESSAGES.setdefault(order_ref, []).append(CardMessage(chat_id, msg.message_id))
    return CARD_MESSAGES[order_ref]


async def refresh_order_card(bot: Bot, order_ref: str, notify: str | None = None) -> None:
    """Re-render from current state and edit every copy. Safe to call any number of times.

    notify: edits are silent, so pass a short line (e.g. "🛵 Rider picked up the order") when the change
    needs attention; it is sent as a NEW message replying to each card, which does alert the admin.
    """
    async with _locks[order_ref]:
        state = await load_order(order_ref)
        if state is None:
            return
        text, markup = render_text(state), render_buttons(state)
        kept = []
        for card in CARD_MESSAGES.get(order_ref, []):
            if await _edit(bot, card, text, markup):
                kept.append(card)
                if notify:
                    await bot.send_message(card.chat_id, notify, reply_to_message_id=card.message_id)
        CARD_MESSAGES[order_ref] = kept


async def _edit(bot: Bot, card: CardMessage, text: str, markup: InlineKeyboardMarkup | None) -> bool:
    """Edit one copy. Returns False when the copy is gone for good and should be forgotten."""
    for attempt in (1, 2):
        try:
            await bot.edit_message_text(text, chat_id=card.chat_id, message_id=card.message_id, reply_markup=markup)
            return True
        except TelegramRetryAfter as e:
            if attempt == 2:
                raise
            log.warning("flood control on chat %s: waiting %ss", card.chat_id, e.retry_after)
            await asyncio.sleep(e.retry_after)
        except TelegramBadRequest as e:
            if "message is not modified" in e.message:
                return True  # state didn't change what the card shows
            if "message to edit not found" in e.message:
                log.warning("card %s deleted in chat %s; forgetting it", card.message_id, card.chat_id)
                return False
            raise
        except TelegramForbiddenError:
            log.warning("bot blocked in chat %s; forgetting its card", card.chat_id)
            return False
    return True
