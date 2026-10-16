"""CardStore: the order-card side of the database (all calls are RPCs, see create_t_order_alerts.sql).

    . RPCs and tables are DEFINED in: ordelo_datamodels/telegram/t_order_alerts.sql
      (keep this list and that file's header in sync whenever either changes)
    . Python method -> RPC it calls:
        snapshot          -> t_order_card_snapshot(p_bot_key, p_order_number, p_order_type)
        card_sent         -> t_order_card_sent(p_bot_key, p_tcid, p_message_id, p_tuid, p_order_number,
                                               p_order_type, p_rest_ref, p_card_status)
        take_for_refresh  -> t_order_cards_take(p_bot_key, p_order_number, p_order_type)
        mark              -> t_order_card_mark(p_id, p_outcome, p_card_status, p_close)
        decide            -> t_order_decide(p_bot_key, p_tuid, p_order_number, p_order_type, p_decision)
        set_pickup        -> t_order_set_pickup(p_bot_key, p_tuid, p_order_number, p_order_type, p_minutes)
      (the last two are defined in ordelo_datamodels/restaurant_admin/restaurant_order_decision.sql; they authorise the
      Telegram USER (tuid) per D14 and then call the shared restaurant_order_decide / restaurant_order_set_pickup)
    . Uses client_ordelo_service (service-role only RPCs); Supabase REST is synchronous, so every call runs
      in asyncio.to_thread (CLAUDE.md rule)
    . Holds no state: any of the gunicorn workers gives the same answers
  Classes/Functions:
    . CardCopy, SentRecord
    . CardStore
"""

import asyncio
from dataclasses import dataclass
from typing import Any, Literal

from config import client_ordelo_service

from .model import Destination, OrderRef, Snapshot, TapOutcome


@dataclass(frozen=True)
class CardCopy:
    """One Telegram message holding a copy of an order card (a t_sent_messages row)."""

    id: int
    tcid: int
    message_id: int
    tuid: int | None = None
    viewer_phone: str | None = None
    authorised: bool = True
    taken_for: Literal["edit", "delete"] = "edit"


@dataclass(frozen=True)
class SentRecord:
    previous: tuple[CardCopy, ...]  # older copies in the same chat, already claimed for deletion
    order_status: str  # the order's status right now ('gone' if it vanished)


async def _rpc(name: str, args: dict) -> Any:
    resp = await asyncio.to_thread(lambda: client_ordelo_service.rpc(name, args).execute())
    return resp.data


class CardStore:
    def __init__(self, bot_key: str):
        self.bot_key = bot_key

    async def snapshot(self, order: OrderRef) -> Snapshot | None:
        data = await _rpc(
            "t_order_card_snapshot",
            {"p_bot_key": self.bot_key, "p_order_number": order.order_number, "p_order_type": order.order_type},
        )
        if data is not None and not isinstance(data, dict):
            raise RuntimeError(f"unexpected t_order_card_snapshot RPC response: {data!r}")
        return Snapshot.from_json(data)

    async def card_sent(
        self, order: OrderRef, rest_ref: str, dest: Destination, message_id: int, card_status: str
    ) -> SentRecord:
        data = await _rpc(
            "t_order_card_sent",
            {
                "p_bot_key": self.bot_key,
                "p_tcid": dest.tcid,
                "p_message_id": message_id,
                "p_tuid": dest.tuid,
                "p_order_number": order.order_number,
                "p_order_type": order.order_type,
                "p_rest_ref": rest_ref,
                "p_card_status": card_status,
            },
        )
        if not isinstance(data, dict) or "order_status" not in data:
            raise RuntimeError(f"unexpected t_order_card_sent RPC response: {data!r}")
        return SentRecord(
            previous=tuple(
                CardCopy(id=p["id"], tcid=p["tcid"], message_id=p["message_id"], taken_for="delete")
                for p in data.get("previous") or ()
            ),
            order_status=data["order_status"],
        )

    async def take_for_refresh(self, order: OrderRef) -> list[CardCopy]:
        data = await _rpc(
            "t_order_cards_take",
            {"p_bot_key": self.bot_key, "p_order_number": order.order_number, "p_order_type": order.order_type},
        )
        if not isinstance(data, dict) or "rows" not in data:
            raise RuntimeError(f"unexpected t_order_cards_take RPC response: {data!r}")
        return [
            CardCopy(
                id=r["id"],
                tcid=r["tcid"],
                message_id=r["message_id"],
                tuid=r.get("tuid"),
                viewer_phone=r.get("viewer_phone"),
                authorised=bool(r.get("authorised", True)),
                taken_for=r.get("taken_for") or "edit",
            )
            for r in data["rows"]
        ]

    async def mark(self, copy_id: int, outcome: str, card_status: str | None, close: bool) -> None:
        await _rpc(
            "t_order_card_mark",
            {"p_id": copy_id, "p_outcome": outcome, "p_card_status": card_status, "p_close": close},
        )

    async def decide(self, tuid: int, order: OrderRef, decision: Literal["accept", "decline"]) -> TapOutcome:
        data = await _rpc(
            "t_order_decide",
            {
                "p_bot_key": self.bot_key,
                "p_tuid": tuid,
                "p_order_number": order.order_number,
                "p_order_type": order.order_type,
                "p_decision": decision,
            },
        )
        return TapOutcome.from_rpc("acc" if decision == "accept" else "dec", data)

    async def set_pickup(self, tuid: int, order: OrderRef, minutes: int) -> TapOutcome:
        data = await _rpc(
            "t_order_set_pickup",
            {
                "p_bot_key": self.bot_key,
                "p_tuid": tuid,
                "p_order_number": order.order_number,
                "p_order_type": order.order_type,
                "p_minutes": minutes,
            },
        )
        return TapOutcome.from_rpc("pk", data)
