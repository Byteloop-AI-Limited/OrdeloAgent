"""ReceiptStore: the receipt side of the database (all calls are RPCs, see restaurant_ready_adjust_notices.sql).

    . RPCs and tables are DEFINED in: ordelo_datamodels/restaurant_admin/restaurant_ready_adjust_notices.sql
      (keep this list and that file's header in sync whenever either changes)
    . Python method -> RPC it calls:
        snapshot          -> t_receipt_snapshot(p_bot_key, p_order_number, p_order_type, p_dispatch_id)
        receipt_sent      -> t_receipt_sent(p_bot_key, p_tcid, p_message_id, p_tuid, p_order_number, p_order_type,
                                            p_rest_ref, p_dispatch_id, p_status)
        take_for_refresh  -> t_receipts_take(p_bot_key, p_order_number, p_order_type)
        mark              -> t_order_card_mark(p_id, p_outcome, p_card_status, p_close)
                             (ordelo_datamodels/telegram/t_sent_messages.sql; generic on t_sent_messages.id, so receipts reuse it)
    . Uses client_ordelo_service (service-role only RPCs); Supabase REST is synchronous, so every call runs
      in asyncio.to_thread (CLAUDE.md rule)
    . Holds no state: any of the gunicorn workers gives the same answers
  Classes/Functions:
    . ReceiptCopy, ReceiptSent
    . ReceiptStore

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . t_order_card_mark (function, ordelo_datamodels/telegram/t_sent_messages.sql): calls (name passed to a helper)
  . t_receipt_sent (function, ordelo_datamodels/restaurant_admin/restaurant_ready_adjust_notices.sql): calls (name passed to a helper)
  . t_receipt_snapshot (function, ordelo_datamodels/restaurant_admin/restaurant_ready_adjust_notices.sql): calls (name passed to a helper)
  . t_receipts_take (function, ordelo_datamodels/restaurant_admin/restaurant_ready_adjust_notices.sql): calls (name passed to a helper)
(end of database objects)
"""

import asyncio
from dataclasses import dataclass
from typing import Any, Literal

from config import client_ordelo_service

from ..order_cards.model import OrderRef
from .model import ReceiptDestination, ReceiptSnapshot


@dataclass(frozen=True)
class ReceiptCopy:
    """One Telegram message holding a copy of a receipt (a t_sent_messages row, kind 'receipt')."""

    id: int
    tcid: int
    message_id: int
    tuid: int | None = None
    viewer_phone: str | None = None
    authorised: bool = True
    taken_for: Literal["edit", "delete"] = "edit"
    dispatch_id: int | None = None


@dataclass(frozen=True)
class ReceiptSent:
    previous: tuple[ReceiptCopy, ...]  # older receipt copies in the same chat, already claimed for deletion
    status: str  # the receipt status key right now ('gone' if the order vanished)


async def _rpc(name: str, args: dict) -> Any:
    resp = await asyncio.to_thread(lambda: client_ordelo_service.rpc(name, args).execute())
    return resp.data


class ReceiptStore:
    def __init__(self, bot_key: str):
        self.bot_key = bot_key

    async def snapshot(self, order: OrderRef, dispatch_id: int | None) -> ReceiptSnapshot | None:
        data = await _rpc(
            "t_receipt_snapshot",
            {"p_bot_key": self.bot_key, "p_order_number": order.order_number, "p_order_type": order.order_type,
             "p_dispatch_id": dispatch_id},
        )
        if data is not None and not isinstance(data, dict):
            raise RuntimeError(f"unexpected t_receipt_snapshot RPC response: {data!r}")
        return ReceiptSnapshot.from_json(data)

    async def receipt_sent(
        self, order: OrderRef, rest_ref: str, dest: ReceiptDestination, message_id: int,
        dispatch_id: int | None, status: str,
    ) -> ReceiptSent:
        data = await _rpc(
            "t_receipt_sent",
            {
                "p_bot_key": self.bot_key, "p_tcid": dest.tcid, "p_message_id": message_id, "p_tuid": dest.tuid,
                "p_order_number": order.order_number, "p_order_type": order.order_type, "p_rest_ref": rest_ref,
                "p_dispatch_id": dispatch_id, "p_status": status,
            },
        )
        if not isinstance(data, dict) or "status" not in data:
            raise RuntimeError(f"unexpected t_receipt_sent RPC response: {data!r}")
        return ReceiptSent(
            previous=tuple(
                ReceiptCopy(id=p["id"], tcid=p["tcid"], message_id=p["message_id"], taken_for="delete")
                for p in data.get("previous") or ()
            ),
            status=data["status"],
        )

    async def take_for_refresh(self, order: OrderRef) -> list[ReceiptCopy]:
        data = await _rpc(
            "t_receipts_take",
            {"p_bot_key": self.bot_key, "p_order_number": order.order_number, "p_order_type": order.order_type},
        )
        if not isinstance(data, dict) or "rows" not in data:
            raise RuntimeError(f"unexpected t_receipts_take RPC response: {data!r}")
        return [
            ReceiptCopy(
                id=r["id"], tcid=r["tcid"], message_id=r["message_id"], tuid=r.get("tuid"),
                viewer_phone=r.get("viewer_phone"), authorised=bool(r.get("authorised", True)),
                taken_for=r.get("taken_for") or "edit", dispatch_id=r.get("dispatch_id"),
            )
            for r in data["rows"]
        ]

    async def mark(self, copy_id: int, outcome: str, card_status: str | None, close: bool) -> None:
        await _rpc(
            "t_order_card_mark",
            {"p_id": copy_id, "p_outcome": outcome, "p_card_status": card_status, "p_close": close},
        )
