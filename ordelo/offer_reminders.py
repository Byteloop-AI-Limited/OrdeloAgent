"""
Telegram rider offer reminders (plans/rider-dispatch-alerts-plan.md, D1-D8).
    . remind(dispatch_id, n, of) -> str  send a fresh copy of one unanswered Telegram offer with "⏰ Still open · reminder n of
      of", move delivery_dispatch.channel_msg_ref to it, delete the previous copy, and redraw the new copy if the job was
      decided meanwhile. Outcome (logs/tests): sent | skipped:<reason> | closed:<reason> | stale | failed
    . escalate(order_number, after_secs, offered, declined) -> bool  one overwatch line when nobody accepted; once per order
      is guaranteed by the SQL ledger; re-checks the order first
    . WHEN an offer may be reminded is decided ONLY by SQL rider_offer_state(); this module never repeats the rules.
    . Never sends on WhatsApp: if the factory falls back (no rider bot / no tcid) the reminder is skipped.
    . Store seam: OfferReminderStore (SupabaseOfferReminderStore = the RPCs; tests use a fake with the same JSON shapes).
  Classes/Functions:
    . Snapshot, Swap, OfferReminderStore, SupabaseOfferReminderStore, reminder_notice, remind, escalate

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . rider_offer_reminder_snapshot (fn, ordelo_datamodels/dispatch/rider_offer_alert.sql): SupabaseOfferReminderStore.snapshot()
  . rider_offer_reminder_sent (fn, ordelo_datamodels/dispatch/rider_offer_alert.sql): SupabaseOfferReminderStore.reminder_sent()
  . rider_offer_order_open (fn, ordelo_datamodels/dispatch/rider_offer_alert.sql): SupabaseOfferReminderStore.order_open()
(end of database objects)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable, Protocol

from loguru import logger

from ordelo.rider_messaging import job_offer, messenger_for
from utils_common.order_management.test_order_dispatch import rider_dispatch_allowed


@dataclass(frozen=True)
class Snapshot:
    """rider_offer_reminder_snapshot(): the state AND everything needed to send."""
    state: str                      # open | quiet | closed
    reason: str | None              # closed: an OfferClosedReason; quiet: why (paused, ...)
    dispatch_id: int
    order_number: str | None = None
    rider_id: str | None = None
    tcid: int | None = None
    msg_ref: str | None = None
    offer: dict[str, Any] | None = None

    @classmethod
    def from_rpc(cls, d: dict[str, Any]) -> "Snapshot":
        return cls(d["state"], d.get("reason"), int(d["dispatch_id"]), d.get("order_number"), d.get("rider_id"),
                   d.get("tcid"), d.get("msg_ref"), d.get("offer"))


@dataclass(frozen=True)
class Swap:
    """rider_offer_reminder_sent(): swapped | stale | gone, plus the state AFTER the send."""
    result: str
    previous_ref: str | None
    state: str
    reason: str | None

    @classmethod
    def from_rpc(cls, d: dict[str, Any]) -> "Swap":
        return cls(d["result"], d.get("previous_ref"), d["state"], d.get("reason"))


class OfferReminderStore(Protocol):
    async def snapshot(self, dispatch_id: int) -> Snapshot: ...
    async def reminder_sent(self, dispatch_id: int, new_ref: str, expected_ref: str | None) -> Swap: ...
    async def order_open(self, order_number: str) -> bool: ...


class SupabaseOfferReminderStore:
    """The RPCs, over the service key (the ledger and functions are revoked from anon; CLAUDE.md rule 5)."""

    def __init__(self, client: Any = None):
        self._client = client

    def _c(self):
        if self._client is None:
            from config import client_ordelo_service
            self._client = client_ordelo_service
        return self._client

    async def _rpc(self, fn: str, params: dict[str, Any]) -> Any:
        return await asyncio.to_thread(lambda: self._c().rpc(fn, params).execute().data)

    async def snapshot(self, dispatch_id: int) -> Snapshot:
        return Snapshot.from_rpc(await self._rpc("rider_offer_reminder_snapshot", {"p_dispatch_id": dispatch_id}))

    async def reminder_sent(self, dispatch_id: int, new_ref: str, expected_ref: str | None) -> Swap:
        return Swap.from_rpc(await self._rpc(
            "rider_offer_reminder_sent", {"p_dispatch_id": dispatch_id, "p_new_ref": new_ref, "p_expected_ref": expected_ref}))

    async def order_open(self, order_number: str) -> bool:
        return bool(await self._rpc("rider_offer_order_open", {"p_order_number": order_number}))


def reminder_notice(n: int, of: int) -> str:
    return f"⏰ Still open · reminder {n} of {of}"


async def _quietly(what: str, aw: Awaitable[Any]) -> None:
    try:
        await aw
    except Exception:
        logger.exception(f"offer reminder: {what} failed")


async def remind(dispatch_id: int, n: int, of: int, *, store: OfferReminderStore | None = None, bot: Any = None) -> str:
    store = store or SupabaseOfferReminderStore()
    snap = await store.snapshot(dispatch_id)                                      # check BEFORE sending
    if snap.state != "open" or snap.offer is None or snap.tcid is None:
        return f"skipped:{snap.reason or snap.state}"
    if not await rider_dispatch_allowed(snap.order_number, snap.rider_id):         # TEST3100 -> overwatch riders only
        return "skipped:not_allowed"
    messenger = messenger_for(snap.rider_id, "telegram", snap.tcid, tg_bot=bot)
    if messenger.channel != "telegram":                                           # factory fell back to WhatsApp
        return "skipped:no_rider_bot"
    try:
        new_ref = await messenger.offer_job(replace(job_offer(snap.offer, dispatch_id), notice=reminder_notice(n, of)))
    except Exception:
        logger.exception(f"offer reminder {dispatch_id}: send failed")
        return "failed"
    swap = await store.reminder_sent(dispatch_id, new_ref, snap.msg_ref)           # move the ref; state AFTER sending
    if swap.result == "stale":                                                    # another reminder won: drop ours
        await _quietly("delete own copy", messenger.delete(new_ref))
        return "stale"
    await _quietly("delete previous copy", messenger.delete(swap.previous_ref))
    reason = swap.reason if swap.state == "closed" else None
    if reason is None:                                                            # a tap on the old copy in between
        again = await store.snapshot(dispatch_id)
        reason = again.reason if again.state == "closed" else None
    if reason:
        await _quietly("close new copy", messenger.offer_closed(new_ref, snap.order_number or "", reason))
        return f"closed:{reason}"
    logger.info(f"offer reminder {dispatch_id}: {n}/{of} sent to {snap.rider_id[-4:]}")
    return "sent"


async def escalate(order_number: str, after_secs: int, offered: int, declined: int, *,
                   store: OfferReminderStore | None = None, alert: Callable[[str], Awaitable[None]] | None = None) -> bool:
    store = store or SupabaseOfferReminderStore()
    if not await store.order_open(order_number):                                  # accepted meanwhile: say nothing
        return False
    if alert is None:
        from channels.telegram.ops_alerts import alert_ops as alert
    mins = f"{after_secs // 60} min" if after_secs % 60 == 0 else f"{after_secs} s"
    await alert(f"⚠️ {order_number}: no rider has accepted after {mins} ({offered} offered on Telegram, {declined} declined)")
    return True
