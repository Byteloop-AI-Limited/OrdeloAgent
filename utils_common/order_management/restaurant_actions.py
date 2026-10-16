"""
Kitchen actions after an order is accepted: Ready and adjust pickup (shared by WhatsApp and Telegram).
    . Thin async wrapper over the database functions (RPCs). The rule lives in SQL so that the first Ready per
      dispatch wins atomically, whichever channel (WhatsApp, Telegram, manual SQL) it comes from.
    . RPCs are DEFINED in: ordelo_datamodels/restaurant_admin/restaurant_ready_adjust_notices.sql
      (keep this list and that file's header in sync whenever either changes)
    . Python function -> RPC it calls:
        ready(ref, WhatsAppActor)          -> restaurant_order_ready(p_order_number, p_order_type, p_admin_phone, p_channel)
        ready(ref, TelegramActor)          -> t_order_ready(p_bot_key, p_tuid, p_order_number, p_order_type)
                                              ok | already_ready | not_ready_state | not_found (| not_authorised, Telegram only)
        adjust_pickup(ref, WhatsAppActor)  -> restaurant_order_adjust_pickup(p_order_number, p_target, p_admin_phone, p_channel)
        adjust_pickup(ref, TelegramActor)  -> t_order_adjust_pickup(p_bot_key, p_tuid, p_order_number, p_minutes)
                                              ok | unchanged | not_ready_state | not_found (| not_authorised, Telegram only)
    . ONLY on 'ok' does ready() run the follow-up, identically for both channels:
        delivery -> the rider agent is told `notify_food_ready_for_pickup` (the text the WhatsApp handler always sent)
        takeaway -> customer event 'ready_for_collection' through customer_notifier.publish (as the handler always did)
      A follow-up that raises is logged and reported as follow_up_failed; the Ready itself stays recorded.
    . An adjust's rider message is NOT sent here: the UPDATE fires trigger_restaurant_updates ->
      delivery_hooks._handle_restaurant_pickuptime_adjusted (unchanged); 'unchanged' writes nothing, so nothing fires.
    . Tables behind them: delivery_summary, takeaway_summary, delivery_inflight, delivery_dispatch
      (the gate is the same rule as ordelo/delivery_progress.check_delivery_progress, evaluated in SQL)
    . Uses client_ordelo_service: the RPCs are service-role only (anon is denied)
    . Supabase REST is synchronous, so every call runs in asyncio.to_thread (CLAUDE.md rule)
    . Authorisation stays with callers for WhatsApp (the sender is an admin by construction); the Telegram wrappers
      authorise in SQL (claimed invite + phone in restaurant_master.admins)
    . Called by: watomation/on_callback_wa_handler.py (admin_collection_ready, admin_takeaway_ready,
      admin_adjust_pickup_time) and channels/telegram/rest_admin/receipts/__init__.py (Receipts.tap)
    . Overview and cross-reference table: docs/telegram-layer.md
  Classes/Functions:
    . WhatsAppActor
    . TelegramActor
    . ActionOutcome
    . ready
    . adjust_pickup
    . not_done_reply_text
    . ready_reply_text
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Literal

from config import client_ordelo_service, logger
from utils_common.notify import customer_notifier
from utils_common.notify.customer_notifier import CustomerOrderEvent

OrderType = Literal["delivery", "takeaway"]
_ORDER_TYPES = frozenset({"delivery", "takeaway"})

READY_RESULTS = frozenset({"ok", "already_ready", "not_ready_state", "not_found", "not_authorised"})
ADJUST_RESULTS = frozenset({"ok", "unchanged", "not_ready_state", "not_found", "not_authorised"})
ADJUST_MINUTES = frozenset({10, 20})


@dataclass(frozen=True)
class WhatsAppActor:
    phone: str  # the sender's WhatsApp number: an admin by construction


@dataclass(frozen=True)
class TelegramActor:
    bot_key: str
    tuid: int  # Telegram user id (from_user.id), never the chat id (D25)


Actor = WhatsAppActor | TelegramActor


@dataclass(frozen=True)
class ActionOutcome:
    result: Literal["ok", "already_ready", "unchanged", "not_ready_state", "not_found", "not_authorised"]
    by_label: str | None = None          # "Ada" / "…0754" (D19): who marked it ready / adjusted
    by_phone: str | None = None
    pickup_time: str | None = None       # ISO string, adjust results
    progress: str | None = None          # 'not_in_progress' | 'picked_up' when not_ready_state
    follow_up_failed: bool = False       # 'ok' in SQL but the rider / customer message raised (logged)


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


def _actor_phone(actor: Actor, data: dict) -> str | None:
    """The admin phone to record on customer events: the WhatsApp sender, or the phone SQL resolved for a Telegram user."""
    return actor.phone if isinstance(actor, WhatsAppActor) else data.get("ready_by_phone")


async def ready(order_number: str, order_type: str, actor: Actor) -> ActionOutcome:
    """Mark the food ready. The first tap per dispatch wins; on 'ok' the rider (or customer) is told."""
    _check_order_type(order_type)
    if isinstance(actor, WhatsAppActor):
        rpc_name = "restaurant_order_ready"
        args = {"p_order_number": order_number, "p_order_type": order_type,
                "p_admin_phone": actor.phone, "p_channel": "whatsapp"}
    else:
        rpc_name = "t_order_ready"
        args = {"p_bot_key": actor.bot_key, "p_tuid": actor.tuid,
                "p_order_number": order_number, "p_order_type": order_type}
    data = _checked(await _rpc(rpc_name, args), rpc_name, READY_RESULTS)
    out = ActionOutcome(result=data["result"], by_label=data.get("ready_by"), by_phone=data.get("ready_by_phone"),
                        progress=data.get("progress"))
    if out.result != "ok":
        return out
    try:
        if order_type == "delivery":
            await _nudge_rider(data["rider_id"], data["rest_name"])
        else:
            await _announce_takeaway_ready(order_number, data, _actor_phone(actor, data))
    except Exception:
        logger.exception(f"restaurant_actions.ready follow-up failed for {order_number} ({order_type})")
        return replace(out, follow_up_failed=True)
    return out


async def _nudge_rider(rider_id: str, rest_name: str) -> None:
    # Imported here: the agent runner is heavy and only this path needs it (takeaway_hooks does the same for queue_release).
    from ordelo.agents.agent_runner import run_rider_agent_w_custom_msg

    await run_rider_agent_w_custom_msg(
        recipient=rider_id,
        human_msg=f"call `tool notify_food_ready_for_pickup`. Rider should hurry to {rest_name} to pickup the food.",
    )


async def _announce_takeaway_ready(order_number: str, data: dict, admin_phone: str | None) -> None:
    order_id = "-".join(order_number.split("-")[1:])
    payload = {
        "order_id": order_id,
        "order_number": order_number,
        "recipient": data.get("recipient") or data.get("customer_id"),
        "admin_id": admin_phone,
        "event": "admin_takeaway_ready",
        "event_dtts": datetime.now(timezone.utc).isoformat(),
    }
    await customer_notifier.publish(
        order_number,
        CustomerOrderEvent("ready_for_collection", "ready_for_collection", "order-takeaway-ready", payload, f"/{order_id}"),
    )


async def adjust_pickup(
    order_number: str, actor: Actor, *, target: str | datetime | None = None, minutes: int | None = None
) -> ActionOutcome:
    """Move a delivery pickup time. WhatsApp passes the absolute `target` its button carries; Telegram passes `minutes`
    (10 or 20, relative to the ORIGINAL pickup, so repeated taps are never cumulative). Delivery only."""
    if isinstance(actor, WhatsAppActor):
        if target is None:
            raise ValueError("WhatsApp adjust needs the absolute target time its button carries")
        if isinstance(target, datetime):
            if target.tzinfo is None:
                raise ValueError("target must be timezone-aware")
            target = target.isoformat()
        rpc_name = "restaurant_order_adjust_pickup"
        args = {"p_order_number": order_number, "p_target": target, "p_admin_phone": actor.phone, "p_channel": "whatsapp"}
    else:
        if minutes not in ADJUST_MINUTES:
            raise ValueError(f"minutes must be 10 or 20, got {minutes!r}")
        rpc_name = "t_order_adjust_pickup"
        args = {"p_bot_key": actor.bot_key, "p_tuid": actor.tuid, "p_order_number": order_number, "p_minutes": minutes}
    data = _checked(await _rpc(rpc_name, args), rpc_name, ADJUST_RESULTS)
    return ActionOutcome(
        result=data["result"], by_label=data.get("by"), by_phone=data.get("by_phone"),
        pickup_time=data.get("pickup_time"), progress=data.get("progress"),
    )


def not_done_reply_text(out: ActionOutcome) -> str:
    """The WhatsApp wording when an action did not run. These are the strings ordelo.delivery_progress.GATE_REPLIES
    always gave, so admins see the same words: no rider on the job (or no such order), food already collected, or a
    state that could not be verified."""
    from ordelo.delivery_progress import GATE_REPLIES, DeliveryProgress

    if out.result == "not_ready_state":
        return GATE_REPLIES[DeliveryProgress.PICKED_UP if out.progress == "picked_up" else DeliveryProgress.NOT_IN_PROGRESS]
    if out.result == "not_found":
        return GATE_REPLIES[DeliveryProgress.NOT_IN_PROGRESS]
    return GATE_REPLIES[DeliveryProgress.UNKNOWN]  # not_authorised, or anything unexpected


def ready_reply_text(out: ActionOutcome) -> str | None:
    """The WhatsApp reply for a Ready tap (None on a clean 'ok': WhatsApp stays silent, as it always did)."""
    if out.result == "ok":
        if out.follow_up_failed:
            return "Marked ready, but the message to the rider could not be sent. Please call the rider."
        return None
    if out.result == "already_ready":
        return f"Already marked ready by {out.by_label}" if out.by_label else "Already marked ready"
    return not_done_reply_text(out)
