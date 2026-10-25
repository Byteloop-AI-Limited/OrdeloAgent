"""
Ops alert shared by the Telegram bots: one line to the overwatch WhatsApp numbers.
    . Never raises: an alert must not break onboarding.
    . Moved here unchanged from channels/telegram/rider/router.py so the rider bot and the restaurant bot use one helper
      (plans/restaurant-admin-roster-onboarding-plan.md, section 5.3).
    . Called by: channels/telegram/rider/router.py, channels/telegram/rest_admin/router.py
  Classes/Functions:
    . alert_ops, mask
"""

from __future__ import annotations

import asyncio

from loguru import logger


async def alert_ops(text: str) -> None:
    """One line to the overwatch WhatsApp numbers (existing WALogger). Never raises: an alert must not break onboarding."""
    try:
        from config.params import get_wa_logger

        wa_logger = await get_wa_logger()
        await asyncio.wait_for(wa_logger.info(text), timeout=10)
    except Exception:
        logger.exception(f"telegram: ops alert failed: {text}")


def mask(phone: str | None) -> str:
    """'…0123' for a phone (never log or send a whole number); '?' when there is none."""
    return f"…{phone[-4:]}" if phone else "?"
