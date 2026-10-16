"""
Plain restaurant notices on Telegram (auto-accepted, rider pickup alert, delivered, customer feedback).
    . Notices.send(rest_ref, text_html, notice=..., order=..., reply_to=...) sends one message to every admin chat of the
      restaurant, optionally as a reply to the order's card or receipt in that chat. No buttons, nothing to edit later.
    . Where it goes and what it replies to is decided in SQL (t_notice_targets, same destinations as order cards, D36);
      each send is recorded for audit (t_notice_sent: a closed t_sent_messages row of kind 'notice').
    . Never raises. Each destination is isolated: a blocked chat costs nobody else their message.
    . RPCs are DEFINED in: ordelo_datamodels/restaurant_admin/restaurant_ready_adjust_notices.sql
      (keep this list and that file's header in sync whenever either changes)
    . Python method -> RPC it calls:
        NoticeStore.targets      -> t_notice_targets(p_bot_key, p_rest_ref, p_order_number, p_reply_kind)
        NoticeStore.notice_sent  -> t_notice_sent(p_bot_key, p_tcid, p_message_id, p_tuid, p_rest_ref, p_order_number, p_notice)
    . Uses client_ordelo_service; Supabase REST is synchronous, so each call runs in asyncio.to_thread
    . Caller: utils_common/notify/restaurant_notifier.py (Telegram adapter). Overview: docs/telegram-layer.md
  Classes/Functions:
    . Notices
    . NoticeStore
"""

import asyncio
from dataclasses import dataclass
from typing import Any, Literal

from aiogram import Bot
from loguru import logger

from config import client_ordelo_service

from .order_cards.io import TelegramIO
from .order_cards.model import OrderRef, View

ReplyKind = Literal["card", "receipt", "none"]


@dataclass(frozen=True)
class NoticeTarget:
    tcid: int
    tuid: int | None
    phone: str | None
    reply_to: int | None  # message to reply to in this chat, None when there is nothing to reply to


async def _rpc(name: str, args: dict) -> Any:
    resp = await asyncio.to_thread(lambda: client_ordelo_service.rpc(name, args).execute())
    return resp.data


class NoticeStore:
    def __init__(self, bot_key: str):
        self.bot_key = bot_key

    async def targets(self, rest_ref: str, order_number: str | None, reply_kind: ReplyKind) -> list[NoticeTarget]:
        data = await _rpc(
            "t_notice_targets",
            {"p_bot_key": self.bot_key, "p_rest_ref": rest_ref, "p_order_number": order_number, "p_reply_kind": reply_kind},
        )
        if not isinstance(data, list):
            raise RuntimeError(f"unexpected t_notice_targets RPC response: {data!r}")
        return [NoticeTarget(r["tcid"], r.get("tuid"), r.get("phone"), r.get("reply_to")) for r in data]

    async def notice_sent(
        self, target: NoticeTarget, message_id: int, rest_ref: str, order_number: str | None, notice: str
    ) -> None:
        await _rpc(
            "t_notice_sent",
            {
                "p_bot_key": self.bot_key, "p_tcid": target.tcid, "p_message_id": message_id, "p_tuid": target.tuid,
                "p_rest_ref": rest_ref, "p_order_number": order_number, "p_notice": notice,
            },
        )


class Notices:
    def __init__(self, bot: Bot, bot_key: str, store: NoticeStore | None = None, io: TelegramIO | None = None):
        self._store = store or NoticeStore(bot_key)
        self._io = io or TelegramIO(bot)
        self._bot_key = bot_key

    async def send(
        self, rest_ref: str, text_html: str, *, notice: str, order: OrderRef | None = None, reply_to: ReplyKind = "none"
    ) -> int:
        """Send `text_html` to every admin chat of `rest_ref`. Returns how many chats received it. Never raises."""
        order_number = order.order_number if order else None
        try:
            targets = await self._store.targets(rest_ref, order_number, reply_to if order else "none")
        except Exception:
            logger.exception(f"telegram[{self._bot_key}]: {notice} notice targets for {rest_ref} failed")
            return 0
        results = await asyncio.gather(*(self._send_one(t, rest_ref, order_number, text_html, notice) for t in targets))
        return sum(results)

    async def _send_one(self, target: NoticeTarget, rest_ref: str, order_number: str | None, text: str, notice: str) -> int:
        try:
            message_id = await self._io.send(target.tcid, View(text, None, True), reply_to=target.reply_to)
            if message_id is None:
                return 0  # bot blocked / chat gone: skip this destination
        except Exception:
            logger.exception(f"telegram[{self._bot_key}]: {notice} notice to chat {target.tcid} failed")
            return 0
        try:
            await self._store.notice_sent(target, message_id, rest_ref, order_number, notice)
        except Exception:  # delivered but not audited: still counts as sent
            logger.exception(f"telegram[{self._bot_key}]: {notice} notice audit row for chat {target.tcid} failed")
        return 1
