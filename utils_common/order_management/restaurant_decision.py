"""
Restaurant decision on an order: accept, decline, choose the pickup time (shared by every channel).
    . Thin async wrapper over the database functions (RPCs). The rule lives in SQL so that the first
      decision wins atomically, whichever channel (WhatsApp, Telegram, manual SQL) it comes from.
    . RPCs are DEFINED in: ordelo_datamodels/restaurant_admin/restaurant_order_decision.sql
      (keep this list and that file's header in sync whenever either changes)
    . Python function -> RPC it calls:
        decide      -> restaurant_order_decide(p_order_number, p_order_type, p_decision, p_admin_phone, p_channel)
                       ok | already_decided | not_found. A decline sets delivery_summary.status = 'declined' in
                       the same UPDATE (R1-a: a declined delivery order is never dispatchable).
        set_pickup  -> restaurant_order_set_pickup(p_order_number, p_order_type, p_pickup_time, p_admin_phone, p_channel)
                       ok | already_set | not_accepted | not_found
      describe() is pure text for the "already decided" reply and calls nothing.
    . Tables behind them: delivery_summary (ordelo_datamodels/delivery/delivery_summary.sql), takeaway_summary
      (ordelo_datamodels/takeaway/takeaway_summary.sql); the "by X" label comes from t_invites (create_t_invites.sql)
    . Called by: watomation/on_callback_wa_handler.py (_update_restaurant_order_status, handle_pickup_time_selection).
      From phase 5 the Telegram buttons reach the same SQL functions through t_order_decide / t_order_set_pickup
      (channels/telegram/rest_admin/order_cards/store.py); 'not_authorised' is only returned there.
    . Uses client_ordelo_service: the RPCs are service-role only (anon is denied)
    . Supabase REST is synchronous, so every call runs in asyncio.to_thread (CLAUDE.md rule)
    . Authorisation stays with callers: these functions trust admin_phone
    . The existing trigger on restaurant_confirmation_status still fires the webhook after a decision, so
      payment, customer messages and the WhatsApp pickup prompts are unchanged.
    . Overview and cross-reference table: docs/telegram-layer.md
  Classes/Functions:
    . DecisionOutcome
    . PickupOutcome
    . decide
    . set_pickup
    . describe
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from config import client_ordelo_service

OrderType = Literal["delivery", "takeaway"]
_ORDER_TYPES = frozenset({"delivery", "takeaway"})
_DECISIONS = frozenset({"accept", "decline"})

DECIDE_RESULTS = frozenset({"ok", "already_decided", "not_found", "not_authorised"})
PICKUP_RESULTS = frozenset({"ok", "already_set", "not_accepted", "not_found", "not_authorised"})


@dataclass(frozen=True)
class DecisionOutcome:
    result: Literal["ok", "already_decided", "not_found", "not_authorised"]  # not_authorised only from phase 5
    decision: str | None = None           # 'accept' | 'decline' when ok
    state: str | None = None              # restaurant_confirmation_status when already_decided
    decided_by: str | None = None         # label (D19): Telegram first name, else '…' + last 4 digits
    decided_by_phone: str | None = None   # lets the order card say "You" to the decider
    pickup_time: str | None = None        # ISO string when already_decided and a pickup is set


@dataclass(frozen=True)
class PickupOutcome:
    result: Literal["ok", "already_set", "not_accepted", "not_found", "not_authorised"]
    state: str | None = None              # restaurant_confirmation_status when not ok
    pickup_time: str | None = None        # the chosen pickup time (ISO string)
    decided_by: str | None = None
    decided_by_phone: str | None = None


async def _rpc(name: str, args: dict) -> Any:
    resp = await asyncio.to_thread(lambda: client_ordelo_service.rpc(name, args).execute())
    return resp.data


def _checked(data: Any, rpc_name: str, allowed: frozenset[str]) -> dict:
    if not isinstance(data, dict) or data.get("result") not in allowed:
        raise RuntimeError(f"unexpected {rpc_name} RPC response: {data!r}")
    return data


def _check_order_type(order_type: str) -> None:
    if order_type not in _ORDER_TYPES:
        raise ValueError(f"order_type must be 'delivery' or 'takeaway', got {order_type!r}")


async def decide(
    order_number: str, order_type: str, decision: str, admin_phone: str, channel: str
) -> DecisionOutcome:
    """Accept or decline an order. The first decision wins; a later caller gets 'already_decided' + who won."""
    _check_order_type(order_type)
    if decision not in _DECISIONS:
        raise ValueError(f"decision must be 'accept' or 'decline', got {decision!r}")
    data = _checked(
        await _rpc(
            "restaurant_order_decide",
            {
                "p_order_number": order_number,
                "p_order_type": order_type,
                "p_decision": decision,
                "p_admin_phone": admin_phone,
                "p_channel": channel,
            },
        ),
        "restaurant_order_decide",
        DECIDE_RESULTS,
    )
    return DecisionOutcome(
        result=data["result"],
        decision=data.get("decision"),
        state=data.get("state"),
        decided_by=data.get("decided_by"),
        decided_by_phone=data.get("decided_by_phone"),
        pickup_time=data.get("pickup_time"),
    )


async def set_pickup(
    order_number: str, order_type: str, pickup_time: str | datetime, admin_phone: str, channel: str
) -> PickupOutcome:
    """Choose the pickup time of an ACCEPTED order. Only the first choice is kept ('already_set' afterwards)."""
    _check_order_type(order_type)
    if isinstance(pickup_time, datetime):
        if pickup_time.tzinfo is None:
            raise ValueError("pickup_time must be timezone-aware")
        pickup_time = pickup_time.isoformat()
    data = _checked(
        await _rpc(
            "restaurant_order_set_pickup",
            {
                "p_order_number": order_number,
                "p_order_type": order_type,
                "p_pickup_time": pickup_time,
                "p_admin_phone": admin_phone,
                "p_channel": channel,
            },
        ),
        "restaurant_order_set_pickup",
        PICKUP_RESULTS,
    )
    return PickupOutcome(
        result=data["result"],
        state=data.get("state"),
        pickup_time=data.get("pickup_time"),
        decided_by=data.get("decided_by"),
        decided_by_phone=data.get("decided_by_phone"),
    )


def describe(state: str, decided_by: str | None) -> str:
    """Words for an order that is already decided: 'accepted by Ada', 'declined', 'auto-accepted (...)'."""
    by = f" by {decided_by}" if decided_by else ""
    if state in ("restaurant_accept", "restaurant_pickuptime_adjusted"):
        return f"accepted{by}"
    if state == "restaurant_decline":
        return f"declined{by}"
    if state in ("restaurant_timedout", "auto_accept"):
        return "auto-accepted (no answer in time)"
    if state == "auto_decline":
        return "auto-declined"
    return "decided"
