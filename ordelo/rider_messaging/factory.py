"""
Build the RiderMessenger for a rider: the one place that decides WHICH channel and WHICH address (D43-D45).
    . for_rider(rider_id): rider_master.channel ('whatsapp' | 'telegram') and tcid. Used for messages that are not part of
      a dispatch: sign-up notices, pause notices (R5), the shift question (R5) and, in R4, the job offer itself (whose
      channel is then copied into delivery_dispatch.channel).
    . for_dispatch(dispatch_id) arrives in phase R3: delivery_dispatch.channel, fixed for the life of that dispatch (D44),
      so a rider whose channel changes mid-job keeps the job's conversation where it started.
    . Telegram needs the rider bot (config.rider_bot) and a tcid. If either is missing (bot not configured, or a row says
      'telegram' without a link) the rider is reached on WhatsApp and a warning is logged: a message is never dropped
      silently.
    . Tests swap the result with use_messenger(fake) (a context manager), like restaurant_notifier.use_adapters.
  Classes/Functions:
    . for_rider
    . messenger_for (pure: channel row -> adapter)
    . use_messenger

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . rider_master (table, ordelo_datamodels/core/rider_master.sql): reads (channel, tcid)
(end of database objects)
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import Any, Iterator

from loguru import logger

from .port import RiderMessenger
from .telegram import TelegramRiderMessenger
from .whatsapp import WhatsAppRiderMessenger

_override: RiderMessenger | None = None


def messenger_for(rider_id: str, channel: str | None, tcid: int | None, *, wa_client: Any = None,
                  tg_bot: Any = None) -> RiderMessenger:
    """Pick the adapter for one rider row. Pure apart from the warning; clients default to the configured ones."""
    if _override is not None:
        return _override
    if channel == "telegram":
        if tg_bot is None:
            from config import rider_bot as tg_bot  # None when the rider bot is not configured (D54)
        if tg_bot is not None and tcid is not None:
            return TelegramRiderMessenger(tg_bot, int(tcid))
        logger.warning(f"rider {rider_id}: channel 'telegram' but {'no rider bot' if tg_bot is None else 'no tcid'};"
                       " using WhatsApp")
    if wa_client is None:
        from config import _async_wa_client as wa_client
    return WhatsAppRiderMessenger(wa_client, rider_id)


async def for_rider(rider_id: str) -> RiderMessenger:
    """The messenger for this rider's current channel (rider_master). Unknown rider -> WhatsApp to that number."""
    if _override is not None:
        return _override
    from config import client_ordelo

    resp = await asyncio.to_thread(
        lambda: client_ordelo.table("rider_master").select("channel, tcid").eq("rider_id", rider_id).limit(1).execute()
    )
    row = (resp.data or [{}])[0]
    return messenger_for(rider_id, row.get("channel"), row.get("tcid"))


@contextmanager
def use_messenger(fake: RiderMessenger) -> Iterator[RiderMessenger]:
    """Tests: every for_rider()/messenger_for() inside the block returns `fake`."""
    global _override
    previous, _override = _override, fake
    try:
        yield fake
    finally:
        _override = previous
