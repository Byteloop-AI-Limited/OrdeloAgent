"""
Telegram kitchen receipts: the receipt an admin sees after a rider accepts (or a takeaway is confirmed), its
Ready / +10 / +20 buttons, and keeping every copy truthful.
    . One deep module, shaped like order_cards (D26). Public names: Receipts (send / refresh / tap)
    . model.py   pure Receipt + snapshot + toasts: ALL receipt text and buttons are composed there
    . store.py   ReceiptStore: the RPCs of ordelo_datamodels/restaurant_admin/restaurant_ready_adjust_notices.sql
    . Sending and editing reuse order_cards/io.TelegramIO (error mapping, 10 s limits, retry-after)
    . The database is authoritative and checked before and after every send (D24); the ledger (t_sent_messages,
      kind 'receipt') only remembers where copies live. A new rider's receipt replaces the old one in each chat (D35).
    . A tap runs restaurant_actions.ready / adjust_pickup (the same rule WhatsApp uses) and then redraws every copy;
      a tap on the status badge ('st') only redraws the copies;
      a WhatsApp tap is caught by the 5-second job job_t_receipt_refresh() -> POST /telegram/rest-admin/order-alerts
    . Callers: utils_common/notify/restaurant_notifier.py (send), watomation/routers/telegram_order_alerts.py (refresh),
      the rest-admin orders router (tap)
    . Overview: docs/telegram-layer.md
  Classes/Functions:
    . Receipts
"""

import asyncio
import time

from aiogram import Bot
from aiogram.types import CallbackQuery
from loguru import logger

from utils_common.order_management import restaurant_actions
from utils_common.order_management.restaurant_actions import TelegramActor

from ...callbacks import OrderAction
from ...replies import answer_quietly
from ..order_cards.io import TelegramIO
from ..order_cards.model import TROUBLE, OrderRef, Viewer
from .model import UP_TO_DATE, Receipt, ReceiptSnapshot, gone_view, receipt_toast, status_kind
from .store import ReceiptCopy, ReceiptStore

__all__ = ["Receipts"]


class _Unread:
    """Marker: the snapshot could not be read (as opposed to None: the order does not exist)."""


_UNREAD = _Unread()


class Receipts:
    def __init__(self, bot: Bot, bot_key: str, store: ReceiptStore | None = None, io: TelegramIO | None = None):
        self._store = store or ReceiptStore(bot_key)
        self._io = io or TelegramIO(bot)
        self._bot_key = bot_key

    async def send(self, order: OrderRef, dispatch_id: int | None = None) -> None:
        """Send the receipt to every destination (as a reply to the order card) and delete this chat's older receipt copies."""
        snap = await self._store.snapshot(order, dispatch_id)  # D24: authoritative check BEFORE sending
        if snap is None or status_kind(snap.status) == "gone":
            return
        if status_kind(snap.status) == "rider_cancelled":
            return  # a late event for a rider who is no longer on the job: never replace the current rider's receipt
        receipt = Receipt.from_snapshot(snap)
        # Destinations are independent chats: send to all at once so a slow chat costs max, not sum (webhook budget).
        changed = await asyncio.gather(*(self._send_one(order, snap, receipt, dest) for dest in snap.destinations))
        if any(changed):  # D24: re-checked AFTER sending; the order moved on mid-send
            await self.refresh(order)

    async def _send_one(self, order: OrderRef, snap: ReceiptSnapshot, receipt: Receipt, dest) -> bool:
        """Send one destination's copy. True when the status moved on meanwhile. Never raises."""
        try:
            view = receipt.view(Viewer(dest.phone, shared=dest.tuid is None))
            sent_id = await self._io.send(dest.tcid, view, reply_to=dest.reply_to)
            if sent_id is None:
                return False  # bot blocked / chat gone: skip this destination
            rec = await self._store.receipt_sent(order, snap.rest_ref, dest, sent_id, snap.dispatch_id, snap.status)
            for prev in rec.previous:
                outcome = await self._io.delete(prev)
                if outcome != "retry":  # retry: stays claimed, the sweep re-offers it
                    await self._store.mark(prev.id, outcome, None, True)
            return rec.status != snap.status
        except Exception:
            logger.exception(f"telegram[{self._bot_key}]: receipt for {order.order_number} to chat {dest.tcid} failed")
            return False

    async def refresh(self, order: OrderRef) -> None:
        """Bring every stale copy of the order's receipt in line with the database."""
        rows = await self._store.take_for_refresh(order)
        if not rows:
            return
        # One snapshot per dispatch (an older rider's copy is drawn for that rider), fetched together.
        dispatches = sorted({r.dispatch_id for r in rows if r.dispatch_id is not None}) or [None]
        snaps = dict(zip(dispatches, await asyncio.gather(*(self._snapshot_quietly(order, d) for d in dispatches))))
        await asyncio.gather(*(self._refresh_one(order, snaps.get(r.dispatch_id), r) for r in rows))

    async def _snapshot_quietly(self, order: OrderRef, dispatch_id: int | None) -> ReceiptSnapshot | None | _Unread:
        """The snapshot; None = the order is really gone; _UNREAD = the database could not be read (try again later)."""
        try:
            return await self._store.snapshot(order, dispatch_id)
        except Exception:
            logger.exception(f"telegram[{self._bot_key}]: receipt snapshot for {order.order_number} failed")
            return _UNREAD

    async def _refresh_one(self, order: OrderRef, snap: ReceiptSnapshot | None | _Unread, row: ReceiptCopy) -> None:
        """Redraw or delete one claimed copy. Logs instead of raising."""
        try:
            if snap is _UNREAD and row.taken_for != "delete":
                return  # a failed read is not 'the order is gone': leave the copy claimed, the sweep offers it again in 30 s
            if row.taken_for == "delete":
                outcome = await self._io.delete(row)
                if outcome != "retry":
                    await self._store.mark(row.id, outcome, None, True)
                return
            if snap is None:
                view, status = gone_view(), "gone"
            else:
                view = Receipt.from_snapshot(snap).view(Viewer(row.viewer_phone, row.authorised, shared=row.tuid is None))
                status = snap.status
            edited = await self._io.edit(row, view)
            if edited != "retry":
                await self._store.mark(row.id, edited, status, view.terminal or edited == "gone")
        except Exception:
            logger.exception(f"telegram[{self._bot_key}]: refresh of receipt {order.order_number} copy {row.id} failed")

    async def tap(self, query: CallbackQuery, action: OrderAction) -> None:
        """Handle a Ready / +10 / +20 tap: authorise and act in SQL, answer the tap, refresh every copy.

        The actor is the Telegram USER (query.from_user.id), never the chat (D27). Every outcome, including
        not_authorised, is shown by refreshing from the database. Never raises to the user.
        """
        order = OrderRef(action.o, "delivery" if action.t == "d" else "takeaway")
        if action.a == "st":  # the status badge: changes nothing, just redraws every copy from the database
            await asyncio.gather(answer_quietly(query, UP_TO_DATE, False), self._refresh_quietly(order))
            return
        actor = TelegramActor(self._bot_key, query.from_user.id)
        t0 = time.monotonic()
        tag = f"telegram[{self._bot_key}]: tap {action.a} on {order.order_number} by tuid={query.from_user.id}"
        logger.info(f"{tag}: start")
        try:
            if action.a == "rdy":
                out = await restaurant_actions.ready(order.order_number, order.order_type, actor)
            else:
                out = await restaurant_actions.adjust_pickup(order.order_number, actor, minutes=action.m)
        except Exception:
            logger.exception(f"{tag} failed after {_ms(t0)}ms")
            await answer_quietly(query, TROUBLE, True)
            return
        logger.info(f"{tag}: outcome={out.result!r} in {_ms(t0)}ms")
        text, alert = receipt_toast(action.a, order.order_type, out)
        # The toast and the redraw are independent: run them together so neither waits for the other.
        await asyncio.gather(answer_quietly(query, text, alert), self._refresh_quietly(order))
        logger.info(f"{tag}: answer + refresh done (total {_ms(t0)}ms)")

    async def _refresh_quietly(self, order: OrderRef) -> None:
        try:
            await self.refresh(order)
        except Exception:
            logger.exception(f"telegram[{self._bot_key}]: refresh after tap on {order.order_number} failed")


def _ms(since: float) -> int:
    return int((time.monotonic() - since) * 1000)
