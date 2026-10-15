"""
Restaurant-admin order buttons: ONE handler for every tap on an order card.
    . build_orders_router() returns a NEW router per call (aiogram routers join only one parent)
    . OrderAction.filter() -> OrderCards.tap(query, callback_data), which authorises the Telegram user in SQL (D14),
      decides, answers the tap and refreshes every copy of the card. All wording lives in order_cards/model.py.
    . `order_cards` is injected from dp["order_cards"] (set in channels/telegram/bots.py, like `tgram_settings`)
  Classes/Functions:
    . build_orders_router
"""

from aiogram import Router
from aiogram.types import CallbackQuery

from ..callbacks import OrderAction
from .order_cards import OrderCards


def build_orders_router() -> Router:
    router = Router(name="rest_admin_orders")

    @router.callback_query(OrderAction.filter())
    async def on_order_action(query: CallbackQuery, callback_data: OrderAction, order_cards: OrderCards):
        await order_cards.tap(query, callback_data)

    return router
