"""Rider job-exit decisions, using the current dispatch status as authority."""
from __future__ import annotations

import asyncio
from enum import Enum
from typing import Protocol

from config import client_ordelo, logger
from channels.telegram.ops_alerts import alert_ops, mask


class Verdict(str, Enum):
    ASK_CONFIRM = "ask_confirm"
    REFUSE = "refuse"
    ALLOW_CLOSE = "allow_close"
    UNKNOWN = "unknown"


def decide(status: str | None) -> Verdict:
    if status == "assigned":
        return Verdict.ASK_CONFIRM
    if status == "pickedup":
        return Verdict.REFUSE
    if status in (None, "declined", "completed", "missed", "unassigned"):
        return Verdict.ALLOW_CLOSE
    return Verdict.UNKNOWN


class DispatchStatusStore(Protocol):
    async def status(self, dispatch_id: int) -> str | None: ...


class SupabaseDispatchStatusStore:
    async def status(self, dispatch_id: int) -> str | None:
        result = await asyncio.to_thread(lambda: client_ordelo.table("delivery_dispatch").select("status").eq("dispatch_id", dispatch_id).execute())
        if not result.data:
            return None
        status = result.data[0].get("status")
        if not isinstance(status, str):
            raise ValueError("dispatch status missing")
        return status


async def verdict_for(dispatch_id: int | None, store: DispatchStatusStore | None = None) -> Verdict:
    if dispatch_id is None:
        return Verdict.ALLOW_CLOSE
    try:
        return decide(await (store or SupabaseDispatchStatusStore()).status(dispatch_id))
    except Exception:
        logger.exception("Could not read dispatch status for job exit")
        return Verdict.UNKNOWN


REFUSE_TEXT = ("I can't cancel or close this job now because the food has already been picked up. "
               "I've let our team know and someone will be in touch with you soon.")


async def refuse_after_pickup(*, messenger, order_number, dispatch_id, rider_name, rider_phone, rider_words, alert=None):
    try:
        await messenger.say(REFUSE_TEXT)
    finally:
        try:
            await (alert or alert_ops)(
                f'⚠️ Rider tried to cancel AFTER pickup · order {order_number} · {rider_name} ({mask(rider_phone)}) '
                f'· dispatch {dispatch_id} is pickedup. Rider said: "{str(rider_words or "")[:200]}". '
                'The agent refused; the job is still with the rider. Please contact them.'
            )
        except Exception:
            logger.exception("Failed to alert overwatch about post-pickup exit")
