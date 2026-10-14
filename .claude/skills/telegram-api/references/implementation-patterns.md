# aiogram 3.31.0 adaptation patterns

Examples describe transport seams, not a complete application. Consult [official links](api-docs.md) for each API. Domain services and identity stores are intentionally application-owned; supply them from Ordelo rather than inventing tables or replacing LangGraph.

## Identity and thread linkage

Resolve `(channel='telegram', bot_id, telegram_user_id)` to the authenticated Ordelo actor; separately resolve the notification destination `chat_id`. Record linkage through an authenticated, expiring, single-use onboarding token. A username or arbitrary submitted phone is not an identity proof. Avoid leaking link tokens/phone details into logs.

For ordinary rider/admin flows prefer private chats; supporting groups requires explicit actor/restaurant authorization, visibility rules and chat/topic routing. Do not overwrite phone-keyed `rider_id`, `customer_id`, `admins` or existing thread rows with Telegram IDs. Account linkage can retain domain IDs while transport-specific state uses separate destinations. LangGraph thread selection must be explicit, with no accidental sharing between WhatsApp, Telegram, restaurants or unrelated jobs. Telegram `message_thread_id` is a chat topic, not a LangGraph checkpoint thread.

Telegram message IDs are scoped to chats. Persist bot/chat/message references per recipient when receipts are sent to several admins; one shared `restaurant_msg_id` cannot represent all chats. This is a migration design requirement, not authorization to execute schema changes.

## Local template and receipt rendering

```python
from html import escape
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions

async def send_payment_prompt(bot: Bot, chat_id: int, name: str,
                              order_id: str, checkout_url: str):
    # checkout_url is the full trusted service-generated URL, including fragment.
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Pay for order", url=checkout_url)
    ]])
    return await bot.send_message(
        chat_id=chat_id,
        text=f"Hi {escape(name)}, payment is ready for order <b>{escape(order_id)}</b>.",
        parse_mode=ParseMode.HTML,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
        reply_markup=markup,
    )
```

Return/store `Message.message_id` with destination. Preserve approved text only after obtaining it; this example does not reproduce the unknown WA template body. For receipts use a renderer aware of entity/HTML boundaries and the 4096-character limit. Do not chop HTML tags arbitrarily. URL buttons do not confirm payment; keep Stripe webhook collection evidence and current order transitions.

## Compact dispatch callback

```python
from typing import Literal
from aiogram import F, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router(name="rider_dispatch")

class DispatchAction(CallbackData, prefix="d1"):
    dispatch_id: int
    action: Literal["a", "d"]

def dispatch_keyboard(dispatch_id: int):
    builder = InlineKeyboardBuilder()
    for label, action in (("Accept", "a"), ("Decline", "d")):
        packed = DispatchAction(dispatch_id=dispatch_id, action=action).pack()
        assert 1 <= len(packed.encode("utf-8")) <= 64
        builder.button(text=label, callback_data=packed)
    builder.adjust(2)
    return builder.as_markup()

@router.callback_query(DispatchAction.filter())
async def handle_dispatch(query: CallbackQuery, callback_data: DispatchAction,
                          identities, delivery_service):
    await query.answer()  # transport acknowledgment, before long work
    if not isinstance(query.message, Message) or query.message.chat.type != "private":
        return  # private-chat example; no domain mutation
    actor = await identities.resolve_telegram(query.from_user.id)
    if actor is None:
        await query.message.answer("Please link your Ordelo account first.")
        return
    outcome = await delivery_service.respond_to_offer(
        actor=actor,
        dispatch_id=callback_data.dispatch_id,
        response="accepted" if callback_data.action == "a" else "declined",
    )
    await query.message.answer(outcome.user_message)
```

The illustrative `identities` and `delivery_service` contracts are not existing Ordelo APIs. Implement the adapter against inspected code: reload the offer/order, verify actor owns the offer and restaurant/role where relevant, retain same-dispatch cancellation logic, and make transition guards atomic under concurrent taps. aiogram dependency injection can supply these objects through middleware/workflow data; it does not create them automatically.

For long JSON, addresses, timestamps, labels or graph instructions use a shared persistent token store. Map an opaque short token to action, order/dispatch, authorized actor(s), original proposal, expiry and replay rules. Token expiry alone is insufficient: check current domain state too. Store before publishing buttons; tokens must survive process restart/multiple workers. A single-use rule is action-specific—do not consume the Accept/Decline cancellation capability prematurely. A UUID/reference in 64 bytes is not permission to execute its payload.

## Location request and input routing

```python
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

async def ask_for_location(bot: Bot, chat_id: int):
    return await bot.send_message(
        chat_id,
        "Please share your current location for this delivery.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Share location", request_location=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )
```

Before sending, persist the authorized pending request; record the prompt Telegram reference after send. Register `@router.message(F.location)` ahead of generic text and map the actual actor. Consume only a matching pending request with valid purpose, active job and time bounds. A reply-keyboard location need not reply to the prompt, so do not demand `reply_to_message` unless the chosen client flow establishes it. Preserve request/dispatch correlation without assuming a WA-specific flag. Remove keyboard with `ReplyKeyboardRemove()` when appropriate. Late unsolicited pins must not invoke unrelated graph work. If handling user live locations, explicitly register `edited_message(F.location)` and deduplicate edits; do not merge them into a one-shot request without an intended policy.

Self-contact input similarly uses `KeyboardButton(request_contact=True)` and `F.contact`; verify contact ownership. Sending a stored customer phone contact is a different operation. Route form replies and commands before generic `F.text` graph messages. FSM input collection should support cancellation/expiry and durable storage if it must survive restart.

## FastAPI webhook seam

```python
import secrets
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import APIRouter, HTTPException, Request

def telegram_routes(bot: Bot, dp: Dispatcher, webhook_secret: str) -> APIRouter:
    if not webhook_secret:
        raise ValueError("A webhook secret is required")
    api = APIRouter()

    @api.post("/telegram/webhook")
    async def telegram_webhook(request: Request):
        supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not secrets.compare_digest(supplied, webhook_secret):
            raise HTTPException(status_code=403, detail="Invalid webhook secret")
        update = Update.model_validate(await request.json(), context={"bot": bot})
        await dp.feed_update(bot, update)
        return {"ok": True}

    return api
```

This synchronous-dispatch seam is useful for short handlers/offline validation; it is not a completed durable ingress. Use explicit awaited send calls in these handlers. If returning `TelegramMethod` objects, handle the dispatch result explicitly; a JSON `ok` does not execute the returned method. `feed_webhook_update` has its own timeout/background behavior, and its result still needs appropriate handling.

For long graph work choose a durable inbox/worker acknowledgment boundary: validate secret/update → insert/deduplicate `(bot_id, update_id)` → return success only after durable acceptance → worker runs authorized domain transitions. Alternatively bound synchronous work and prove duplicate protection before Telegram retries. Callback-query ID does not replace domain idempotency under distinct repeated taps. Per-job serialization or DB atomic guards may be needed with multiple workers.

Merge Bot/Dispatcher creation and teardown into the current FastAPI lifespan; close bot sessions/FSM resources. Use `DefaultBotProperties` for defaults. Include routers before computing `resolve_used_update_types()`. Register `set_webhook(..., secret_token=..., drop_pending_updates=False)` only during an authorized configuration action; do not include bot token in route path. Preserve pending updates and avoid deleting the production webhook at routine shutdown. Polling requires webhook removal and a separate development bot or approved switch.

Separate inbound anti-spam from outbound Bot API rate limiting. Acknowledge callbacks even when middleware rejects/throttles them. For explicit `TelegramRetryAfter`, respect server delay and bounded retries; for ambiguous timeouts avoid blindly duplicating sent receipts/offers. Keep logs tied to order/update/message references without secrets.
