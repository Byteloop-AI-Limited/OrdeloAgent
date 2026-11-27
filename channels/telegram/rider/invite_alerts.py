"""Deliver durable invite claim alerts to the existing WhatsApp overwatch channel.

sweep_pending() is woken by pg_cron (job_rider_invite_alerts → POST /rider-hooks/invite-alerts,
watomation/routers/sweep_hooks.py). There is no in-process loop (ADR 0019).
"""

import asyncio
from uuid import uuid4

from loguru import logger

from .. import rider_invites


def alert_text(alert: rider_invites.RiderInviteAlert) -> str:
    current = f"@{alert.username}" if alert.username else str(alert.tuid)
    text = f"ℹ️ - Rider bot: personal invite claimed for …{alert.phone_tail} by Telegram {current}."
    if alert.previous_tuid is not None:
        previous = f"@{alert.previous_username}" if alert.previous_username else str(alert.previous_tuid)
        text += f" Previous Telegram account: {previous}."
    return text


async def _deliver(alert: rider_invites.RiderInviteAlert) -> tuple[str, list[str]]:
    from config import _async_wa_client
    from config.params import get_overwatch_list

    try:
        recipients = set(await asyncio.wait_for(asyncio.to_thread(get_overwatch_list), timeout=10))
    except Exception:
        return "retry", []
    if not recipients:
        return "retry", []

    pending = sorted(recipients.difference(alert.accepted))
    text = alert_text(alert)
    results = await asyncio.gather(*(
        asyncio.wait_for(_async_wa_client.send_message(to=recipient, text=text), timeout=10)
        for recipient in pending
    ), return_exceptions=True)
    accepted = [recipient for recipient, result in zip(pending, results) if not isinstance(result, BaseException)]
    return ("accepted" if len(accepted) == len(pending) else "ambiguous"), accepted


async def sweep_pending() -> int:
    """Drain a bounded batch. Called from the cron-woken hook; a crash leaves a recoverable database lease."""
    processed = 0
    for _ in range(20):
        lease = uuid4()
        alert = await rider_invites.take_alert(lease)
        if alert is None:
            break
        logger.info("telegram[rider]: invite alert update {} claimed by sweep", alert.update_id)
        result, accepted = await _deliver(alert)
        finished = await rider_invites.finish_alert(alert.update_id, lease, result, accepted)
        if result != "accepted" or finished != "ok":
            logger.warning("telegram[rider]: invite alert update {} transport={} recorded={}",
                           alert.update_id, result, finished)
        processed += 1
    return processed
