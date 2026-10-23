"""
Restaurant-admin order buttons: ONE handler for every tap on an order card.
    . build_orders_router() returns a NEW router per call (aiogram routers join only one parent)
    . OrderAction.filter() -> accept / decline / pickup time (a = acc | dec | pk) go to OrderCards.tap;
      Ready, +10/+20 and the status badge (a = rdy | adj | st) go to Receipts.tap. Both authorise the Telegram user in SQL (D14), act,
      answer the tap and refresh every copy. All wording lives in order_cards/model.py and receipts/model.py.
    . `order_cards` and `receipts` are injected from dp["order_cards"] / dp["receipts"] (set in channels/telegram/bots.py,
      like `tgram_settings`)
  Classes/Functions:
    . build_orders_router
"""

from aiogram import Router
from aiogram.types import CallbackQuery, Update

from config.tgram_setting import TgramBotSettings

from ..callbacks import OrderAction
from ..inbox import process_once
from .order_cards import OrderCards
from .receipts import Receipts


def build_orders_router() -> Router:
    router = Router(name="rest_admin_orders")

    @router.callback_query(OrderAction.filter())
    async def on_order_action(
        query: CallbackQuery, callback_data: OrderAction, order_cards: OrderCards, receipts: Receipts,
        tgram_settings: TgramBotSettings, event_update: Update,
    ):
        async def work():
            if callback_data.a in ("rdy", "adj", "st"):
                await receipts.tap(query, callback_data)
            else:
                await order_cards.tap(query, callback_data)

        await process_once(tgram_settings.bot_key, event_update, query.from_user.id, work)

    return router
