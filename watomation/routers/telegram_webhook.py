"""
Telegram webhook ingress for OrdeloAgent (thin route; logic lives in channels/telegram).
    . POST /telegram/{bot_slug}/webhook, e.g. /telegram/rest-admin/webhook
    . 404 for unknown bots, 403 for a wrong X-Telegram-Bot-Api-Secret-Token
    . Acknowledges at once (200) and feeds the update to that bot's own Dispatcher in a BackgroundTask with a
      timeout. Telegram delivers a bot's webhook updates one at a time, so handling inline would let one slow
      Telegram/DB call stall every later tap of that bot (the 25 s hang seen on answerCallbackQuery).
    . Consequence: updates of one bot may now run concurrently, so ordering is not guaranteed. Order actions are
      atomic SQL functions, so this is safe for taps; multi-step FSM flows from one user are the one thing to watch.
    . Always 200 after the secret check: Telegram retries non-2xx and a failing update would loop
    . Selected consequential handlers deduplicate through channels/telegram/inbox.py; other updates run without an inbox claim
"""

import asyncio
import secrets
import time

from aiogram.types import Update
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from loguru import logger
from pydantic import ValidationError

from channels.telegram.bots import find_by_slug

router = APIRouter(tags=["telegram"])

HANDLER_TIMEOUT_SECS = 25


@router.post("/telegram/{bot_slug}/webhook", include_in_schema=False)
async def telegram_webhook(
    bot_slug: str,
    request: Request,
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: str = Header(default=""),
):
    tg = find_by_slug(getattr(request.app.state, "telegram_bots", {}), bot_slug)
    if tg is None:
        raise HTTPException(404, "unknown bot")
    expected = tg.settings.webhook_secret.get_secret_value().encode()
    if not secrets.compare_digest(x_telegram_bot_api_secret_token.encode(), expected):
        raise HTTPException(403, "bad secret")

    payload = await request.json()
    try:
        update = Update.model_validate(payload, context={"bot": tg.bot})
    except ValidationError:
        update_id = payload.get("update_id") if isinstance(payload, dict) else None
        logger.warning(f"telegram[{tg.key}]: invalid update {update_id}")
        return {"ok": True}

    background_tasks.add_task(_handle_update, tg, update)
    return {"ok": True}


async def _handle_update(tg, update: Update) -> None:
    # Timing: `delivery_lag` = Telegram's message timestamp -> our receipt is no longer measurable here (the
    # route acks first); `handled_ms` = our own processing time (large => slow handler/DB/send).
    started = time.monotonic()
    try:
        await asyncio.wait_for(tg.dp.feed_update(tg.bot, update), timeout=HANDLER_TIMEOUT_SECS)
    except Exception:  # includes TimeoutError
        logger.exception(f"telegram[{tg.key}]: handler failed for update {update.update_id}")
    logger.info(f"telegram[{tg.key}]: update {update.update_id} handled_ms={(time.monotonic() - started) * 1000:.0f}")
