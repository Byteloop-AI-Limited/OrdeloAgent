"""
Telegram order cards: the order alert an admin sees, its reminders, and keeping every copy truthful.
    . One deep module (D26). Public names: OrderCards (remind / refresh / tap) and OrderRef.
    . model.py   pure Card + events + views + toasts: ALL text and buttons are composed there
    . store.py   CardStore: the RPCs of ordelo_datamodels/migrations/create_t_order_alerts.sql
    . io.py      TelegramIO: send / edit / delete with Telegram error mapping
    . The database is authoritative and checked before every send (D24); the ledger (t_sent_messages) only
      remembers where copies live so they can be tidied up. Nothing is held in process (up to 3 workers).
    . Callers: watomation/routers/telegram_order_alerts.py (remind, refresh), the rest-admin orders router (tap)
    . Overview: docs/telegram-layer.md
  Classes/Functions:
    . OrderCards
"""

import asyncio
import time

from aiogram import Bot
from aiogram.types import CallbackQuery
from loguru import logger

from ...callbacks import OrderAction
from ...replies import answer_quietly
from .io import TelegramIO
from .model import TROUBLE, Card, Facts, OrderRef, Reminded, Viewer, toast
from .store import CardStore

__all__ = ["OrderCards", "OrderRef"]


class OrderCards:
    def __init__(self, bot: Bot, bot_key: str, store: CardStore | None = None, io: TelegramIO | None = None):
        self._store = store or CardStore(bot_key)
        self._io = io or TelegramIO(bot)
        self._bot_key = bot_key

    async def remind(self, order: OrderRef, n: int, of: int) -> None:
        """Send a fresh copy of the card to every destination and delete the previous copy in each chat."""
        snap = await self._store.snapshot(order)  # D24: authoritative check BEFORE sending
        if snap is None or snap.status != "awaiting" or snap.facts is None:
            return await self.refresh(order)  # decided meanwhile: tidy up instead of nagging
        card = Card.from_snapshot(snap).apply(Reminded(n, of))
        # Destinations are independent chats: send to all at once so a slow chat costs max, not sum (webhook budget).
        decided = await asyncio.gather(*(self._remind_one(order, snap, card, dest) for dest in snap.destinations))
        if any(decided):  # D24: re-checked AFTER sending; decided mid-send
            await self.refresh(order)

    async def _remind_one(self, order: OrderRef, snap, card: Card, dest) -> bool:
        """Send one destination's copy. True when the order turned out to be decided meanwhile. Never raises."""
        try:
            sent_id = await self._io.send(dest.tcid, card.view(Viewer(dest.phone, shared=dest.tuid is None)))
            if sent_id is None:
                return False  # bot blocked / chat gone: skip this destination
            rec = await self._store.card_sent(order, snap.rest_ref, dest, sent_id, card.status)
            for prev in rec.previous:
                outcome = await self._io.delete(prev)
                if outcome != "retry":  # retry: stays claimed, the sweep re-offers it
                    await self._store.mark(prev.id, outcome, None, True)
            return rec.order_status != "awaiting"
        except Exception:
            logger.exception(f"telegram[{self._bot_key}]: reminder for {order.order_number} to chat {dest.tcid} failed")
            return False

    async def refresh(self, order: OrderRef) -> None:
        """Bring every stale copy of the order's card in line with the database."""
        snap = await self._store.snapshot(order)
        card = Card.from_snapshot(snap) if snap is not None and snap.facts is not None else None
        rows = await self._store.take_for_refresh(order)
        # Copies live in different chats: redraw them at once so the pass costs one slow call, not the sum.
        await asyncio.gather(*(self._refresh_one(order, snap, card, row) for row in rows))

    async def _refresh_one(self, order: OrderRef, snap, card: Card | None, row) -> None:
        """Redraw or delete one claimed copy. Never raises."""
        try:
            if row.taken_for == "delete":
                outcome = await self._io.delete(row)
                if outcome != "retry":
                    await self._store.mark(row.id, outcome, None, True)
                return
            view = (card or Card.vanished(_placeholder_facts(order))).view(
                Viewer(row.viewer_phone, row.authorised, shared=row.tuid is None)
            )
            edited = await self._io.edit(row, view)
            if edited != "retry":
                await self._store.mark(row.id, edited, snap.status if snap else "gone", view.terminal or edited == "gone")
        except Exception:
            logger.exception(f"telegram[{self._bot_key}]: refresh of {order.order_number} copy {row.id} failed")

    async def tap(self, query: CallbackQuery, action: OrderAction) -> None:
        """Handle an Accept / Decline / pickup-time tap: authorise and decide in SQL, answer the tap, refresh copies.

        The actor is the Telegram USER (query.from_user.id), never the chat (D27). Every outcome, including
        not_authorised, is shown by refreshing from the database, so the tapper's copy and everyone else's
        copies end up showing what the database says. Never raises to the user.
        """
        order = OrderRef(action.o, "delivery" if action.t == "d" else "takeaway")
        t0 = time.monotonic()
        tag = f"telegram[{self._bot_key}]: tap {action.a} on {order.order_number} by tuid={query.from_user.id}"
        logger.info(f"{tag}: start")
        try:
            if action.a == "pk":
                outcome = await self._store.set_pickup(query.from_user.id, order, action.m)
            else:
                outcome = await self._store.decide(
                    query.from_user.id, order, "accept" if action.a == "acc" else "decline"
                )
        except Exception:
            logger.exception(f"{tag} failed after {_ms(t0)}ms")
            await answer_quietly(query, TROUBLE, True)
            return
        logger.info(f"{tag}: decided outcome={outcome!r} in {_ms(t0)}ms")
        text, alert = toast(outcome)
        # The toast and the redraw are independent: run them together so neither waits for the other. Both are
        # bounded (answer_quietly 3 s, each Bot API call 10 s) and neither raises past here.
        t1 = time.monotonic()
        await asyncio.gather(answer_quietly(query, text, alert), self._refresh_quietly(order))
        logger.info(f"{tag}: answer + refresh took {_ms(t1)}ms (total {_ms(t0)}ms)")

    async def _refresh_quietly(self, order: OrderRef) -> None:
        try:
            await self.refresh(order)
        except Exception:
            logger.exception(f"telegram[{self._bot_key}]: refresh after tap on {order.order_number} failed")


def _ms(since: float) -> int:
    return int((time.monotonic() - since) * 1000)


def _placeholder_facts(order: OrderRef) -> Facts:
    from datetime import datetime, timezone

    return Facts(order.order_number, order.order_type, "", "", (), datetime.now(timezone.utc))
