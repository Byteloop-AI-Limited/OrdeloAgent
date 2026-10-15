"""
Telegram webhook ingress for OrdeloAgent (thin route; logic lives in channels/telegram).
    . POST /telegram/{bot_slug}/webhook, e.g. /telegram/rest-admin/webhook
    . 404 for unknown bots, 403 for a wrong X-Telegram-Bot-Api-Secret-Token
    . Feeds the update to that bot's own Dispatcher inline with a timeout
    . Always 200 after the secret check: Telegram retries non-2xx and a failing update would loop
    . STEP-1 ONLY: no durable inbox. telegram_inbox must exist before any state-changing handler (ADR 0011).
"""

import asyncio
import secrets
import time
from datetime import datetime, timezone

from aiogram.types import Update
from fastapi import APIRouter, Header, HTTPException, Request
from loguru import logger
from pydantic import ValidationError

from channels.telegram.bots import find_by_slug

router = APIRouter(tags=["telegram"])

HANDLER_TIMEOUT_SECS = 25


@router.post("/telegram/{bot_slug}/webhook", include_in_schema=False)
async def telegram_webhook(
    bot_slug: str,
    request: Request,
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

    # Timing: `delivery_lag` = Telegram's message timestamp -> our receipt (large => delay is before us:
    # Telegram retries, tunnel, DNS). `handled_ms` = our own processing time (large => slow handler/DB/send).
    msg = update.message
    delivery_lag = f"{(datetime.now(timezone.utc) - msg.date).total_seconds():.1f}s" if msg else "n/a"
    started = time.monotonic()
    try:
        await asyncio.wait_for(tg.dp.feed_update(tg.bot, update), timeout=HANDLER_TIMEOUT_SECS)
    except Exception:  # includes TimeoutError
        logger.exception(f"telegram[{tg.key}]: handler failed for update {update.update_id}")
    logger.info(
        f"telegram[{tg.key}]: update {update.update_id} delivery_lag={delivery_lag} "
        f"handled_ms={(time.monotonic() - started) * 1000:.0f}"
    )
    return {"ok": True}
