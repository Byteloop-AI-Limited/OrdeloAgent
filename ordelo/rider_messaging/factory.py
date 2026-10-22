"""
Build the RiderMessenger for a rider: the one place that decides WHICH channel and WHICH address (D43-D45).
    . for_rider(rider_id): rider_master.channel ('whatsapp' | 'telegram') and tcid. Used for messages that are not part of
      a dispatch: sign-up notices, pause notices (R5), the shift question (R5) and, in R4, the job offer itself (whose
      channel is then copied into delivery_dispatch.channel).
    . for_dispatch(dispatch_id) (R3): delivery_dispatch.channel, fixed for the life of that dispatch (D44), so a rider whose
      channel changes mid-job keeps the job's conversation where it started. dispatch_channel() returns the same facts plus
      the offer's message ref (channel_msg_ref) for offer_closed().
    . for_thread(thread) (R3): the agent's messenger for a rider thread; the thread snapshot already carries the dispatch's
      channel and the rider's tcid (agent_threads/rider_threads.sql), so no extra query. A thread opened before R2 has no
      dispatch row: WhatsApp, as before.
    . Every builder takes an optional wa_client so callers that hold their own pywa client (and tests that patch it) keep
      using it on the WhatsApp side.
    . Telegram needs the rider bot (config.rider_bot) and a tcid. If either is missing (bot not configured, or a row says
      'telegram' without a link) the rider is reached on WhatsApp and a warning is logged: a message is never dropped
      silently.
    . Tests swap the result with use_messenger(fake) (a context manager), like restaurant_notifier.use_adapters.
  Classes/Functions:
    . for_rider, for_dispatch, for_thread, dispatch_channel, DispatchChannel
    . messenger_for (pure: channel row -> adapter)
    . use_messenger

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . rider_master (table, ordelo_datamodels/core/rider_master.sql): reads (channel, tcid)
  . delivery_dispatch (table, ordelo_datamodels/dispatch/delivery_dispatch.sql): reads (channel, channel_msg_ref, rider_id)
(end of database objects)
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
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


async def _rider_row(rider_id: str) -> dict:
    from config import client_ordelo

    resp = await asyncio.to_thread(
        lambda: client_ordelo.table("rider_master").select("channel, tcid").eq("rider_id", rider_id).limit(1).execute()
    )
    return (resp.data or [{}])[0]


async def for_rider(rider_id: str, *, wa_client: Any = None) -> RiderMessenger:
    """The messenger for this rider's current channel (rider_master). Unknown rider -> WhatsApp to that number."""
    if _override is not None:
        return _override
    row = await _rider_row(rider_id)
    return messenger_for(rider_id, row.get("channel"), row.get("tcid"), wa_client=wa_client)


@dataclass(frozen=True)
class DispatchChannel:
    """Where one offer / job lives: its rider, channel (fixed at offer time), the rider's Telegram chat and the offer ref."""

    dispatch_id: int
    rider_id: str
    channel: str = "whatsapp"
    tcid: int | None = None
    msg_ref: str | None = None
    order_number: str | None = None
    status: str | None = None


async def dispatch_channel(dispatch_id: int) -> DispatchChannel | None:
    """delivery_dispatch (channel, channel_msg_ref, rider_id, order_number, status) + rider_master.tcid; None if no such row."""
    from config import client_ordelo

    resp = await asyncio.to_thread(
        lambda: client_ordelo.table("delivery_dispatch")
        .select("dispatch_id, rider_id, channel, channel_msg_ref, order_number, status")
        .eq("dispatch_id", dispatch_id)
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    if not rows:
        return None
    row = rows[0]
    channel = row.get("channel") or "whatsapp"
    tcid = (await _rider_row(row["rider_id"])).get("tcid") if channel == "telegram" else None
    return DispatchChannel(int(row["dispatch_id"]), row["rider_id"], channel, tcid, row.get("channel_msg_ref"),
                           row.get("order_number"), row.get("status"))


def messenger_for_dispatch(dc: DispatchChannel, *, wa_client: Any = None) -> RiderMessenger:
    return messenger_for(dc.rider_id, dc.channel, dc.tcid, wa_client=wa_client)


async def for_dispatch(dispatch_id: int, *, rider_id: str | None = None, wa_client: Any = None) -> RiderMessenger:
    """The messenger for this dispatch's channel (D44). An unknown dispatch falls back to WhatsApp to rider_id."""
    if _override is not None:
        return _override
    dc = await dispatch_channel(dispatch_id)
    if dc is None:
        if rider_id is None:
            raise LookupError(f"dispatch {dispatch_id} not found and no rider_id to fall back to")
        return messenger_for(rider_id, "whatsapp", None, wa_client=wa_client)
    return messenger_for_dispatch(dc, wa_client=wa_client)


def for_thread(thread: Any, *, wa_client: Any = None) -> RiderMessenger:
    """The agent's messenger for a rider thread (ordelo.agents.rider_threads.RiderThread): its dispatch's channel."""
    return messenger_for(thread.rider_id, thread.channel, thread.tcid, wa_client=wa_client)


@contextmanager
def use_messenger(fake: RiderMessenger) -> Iterator[RiderMessenger]:
    """Tests: every for_rider()/messenger_for() inside the block returns `fake`."""
    global _override
    previous, _override = _override, fake
    try:
        yield fake
    finally:
        _override = previous
