"""HTTP side of the mini app. Mounted by app.py. Auth = Telegram's signed initData in the
`X-Telegram-Init-Data` header on every API call; the user id always comes from the VERIFIED data,
never from the request body or query string."""
import logging
import time
from pathlib import Path
from typing import Annotated

from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import invites
from . import store
from .auth import InitDataError, validate_init_data

log = logging.getLogger(__name__)
router = APIRouter(prefix="/miniapp", tags=["miniapp"])
STATIC = Path(__file__).parent / "static"


def current_user(request: Request, x_telegram_init_data: Annotated[str, Header()] = "") -> dict:
    s = request.app.state.settings
    try:
        return validate_init_data(x_telegram_init_data, s.bot_token, s.miniapp_auth_max_age)
    except InitDataError as e:
        raise HTTPException(401, f"invalid Telegram initData: {e}") from None


User = Annotated[dict, Depends(current_user)]


@router.get("/", include_in_schema=False)
async def page():
    # no-store: during development you always want the latest page inside Telegram's webview
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


@router.get("/api/session")
async def session(user: User):
    """What the SERVER verified about the caller (compare with the page's unverified initDataUnsafe)."""
    linked = invites.find_by_telegram_user(user["user_id"])
    return {
        "user": {k: user["user"].get(k) for k in ("id", "first_name", "last_name", "username", "language_code")},
        "auth_age_seconds": max(0, int(time.time()) - user["auth_date"]),
        "ordelo_link": None if not linked else {"phone": "+" + linked["phone_number"], "phone_verified": linked["phone_verified"]},
    }


@router.get("/api/menu")
async def menu(user: User):
    return store.MENU


class LineIn(BaseModel):
    id: str = Field(max_length=32)
    qty: int


class OrderIn(BaseModel):
    items: list[LineIn] = Field(max_length=store.MAX_LINES)
    idempotency_key: str = Field(min_length=8, max_length=64)


@router.post("/api/orders")
async def place_order(body: OrderIn, request: Request, user: User):
    try:
        order, created = store.create_order(user["user_id"], [store.Line(i.id, i.qty) for i in body.items], body.idempotency_key)
    except store.OrderError as e:
        raise HTTPException(422, str(e)) from None
    notified = False
    if created:  # a retry of the same key must not send a second chat message
        notified = await _notify(request, user["user_id"], order)
    return {"order": store.public_view(order), "created": created, "chat_notified": notified}


@router.get("/api/orders")
async def my_orders(user: User):
    return store.orders_for(user["user_id"])


@router.get("/api/orders/{order_id}")
async def my_order(order_id: str, user: User):
    order = store.get_order_for(user["user_id"], order_id)
    if order is None:
        raise HTTPException(404, "order not found")
    return order


async def _notify(request: Request, chat_id: int, order: dict) -> bool:
    """Confirm in the bot chat with a button that reopens the mini app on this order.
    A private chat id equals the user id; this fails if the user never started / blocked the bot."""
    s = request.app.state.settings
    kb = None
    if s.miniapp_url.startswith("https://"):
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text="Track order", web_app=WebAppInfo(url=f"{s.miniapp_url.rstrip('/')}/?order={order['id']}"))]])
    try:
        await request.app.state.bot.send_message(
            chat_id, f"✅ Order <b>{order['id']}</b> received: £{order['total'] / 100:.2f}", reply_markup=kb)
        return True
    except TelegramAPIError:
        log.warning("Could not message user %s about order %s", chat_id, order["id"], exc_info=True)
        return False
