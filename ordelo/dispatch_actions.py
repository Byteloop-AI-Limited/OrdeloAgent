"""
Dispatch actions: what happens when a rider answers a job offer, on any channel (D48), and closing offers (D49).
    . respond_to_offer(rider_id, dispatch_id, order_number, accept) -> OfferOutcome. The rules that lived inside the WhatsApp
      handler (watomation/on_callback_wa_handler.dispatch_response + agent_app_handlers.initial_handle_of_rider_response),
      unchanged and in the same order:
        1. no delivery_summary row for the order                                  -> gone
        2. the order is inflight:
             with this rider, and this is NOT a decline of the same dispatch       -> already_on_this_job
             with this rider, and it IS a decline of the same dispatch             -> step 3 (cancel before pickup)
             with another rider                                                   -> taken
        3. decline: the dispatch is still 'assigned' -> the rider agent runs its cancel-before-pickup tool -> cancel_own_job
                    otherwise the offer row becomes 'declined' (from unassigned / accepted)               -> declined
        4. accept:  order 'unassigned'            -> dispatch 'accepted' (job_assign_dispatch picks the winner) -> accepted
                    order 'completed' / 'timedout' -> gone ;  anything else -> ignored (no message today)
      The WhatsApp handler maps outcomes to its existing texts (whatsapp_reply); the Telegram rider bot edits the offer.
      Race-hardening of assignment (ADR 0011 point 4) is deliberately NOT part of this extraction (D48).
    . close_open_offers(order_number, reason, statuses, winner_dispatch_id) edits still-open TELEGRAM offers of an order
      (assignment: 'taken' for unanswered offers and 'assigned' for the winner; order timed out: 'expired'). WhatsApp offers
      are left exactly as today (they cannot be edited, and no new WhatsApp text is added).
    . record_offer_ref(dispatch_id, ref) stores the offer's MsgRef on delivery_dispatch.channel_msg_ref.
  Classes/Functions:
    . OfferOutcome, respond_to_offer, whatsapp_reply
    . close_open_offers, record_offer_ref

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . delivery_summary (table, ordelo_datamodels/delivery/delivery_summary.sql): reads (status)
  . delivery_inflight (table, ordelo_datamodels/dispatch/delivery_inflight.sql): reads
  . delivery_dispatch (table, ordelo_datamodels/dispatch/delivery_dispatch.sql): reads, updates (status, channel_msg_ref)
(end of database objects)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from config import client_ordelo, logger

GONE = "gone"
ALREADY_ON_THIS_JOB = "already_on_this_job"
TAKEN = "taken"
CANCEL_OWN_JOB = "cancel_own_job"
DECLINED = "declined"
ACCEPTED = "accepted"
IGNORED = "ignored"


@dataclass(frozen=True)
class OfferOutcome:
    result: str
    order_number: str
    dispatch_id: int
    inflight_order: str | None = None  # the job the rider is already on (already_on_this_job)


# WhatsApp texts, verbatim from the handler they came from (watomation/on_callback_wa_handler.py, agent_app_handlers.py).
_WHATSAPP_TEXTS = {
    GONE: "Sorry, This job is no longer available",
    TAKEN: "Sorry, this job was picked up by another rider.",
}


def whatsapp_reply(out: OfferOutcome) -> str | None:
    """The WhatsApp text for an outcome, exactly as before; None where WhatsApp said nothing."""
    if out.result == ALREADY_ON_THIS_JOB:
        return f"Sorry, You are already on a job {out.inflight_order}"
    return _WHATSAPP_TEXTS.get(out.result)


async def _select(table: str, columns: str, **eq) -> list[dict]:
    def run():
        q = client_ordelo.table(table).select(columns)
        for k, v in eq.items():
            q = q.eq(k, v)
        return q.execute().data or []

    return await asyncio.to_thread(run)


async def respond_to_offer(rider_id: str, dispatch_id: int, order_number: str, accept: bool) -> OfferOutcome:
    """Apply a rider's Accept / Decline to one offer. Same rules on every channel; see the module docstring."""

    def outcome(result: str, inflight_order: str | None = None) -> OfferOutcome:
        return OfferOutcome(result, order_number, dispatch_id, inflight_order)

    summary = await _select("delivery_summary", "status", order_number=order_number)
    if not summary:
        logger.error(f"No delivery detail found for order number: {order_number}")
        return outcome(GONE)

    inflight = await _select("delivery_inflight", "*", order_number=order_number)
    if inflight:
        row = inflight[0]
        if row["rider_id"] == rider_id:
            same_dispatch_decline = (not accept) and row.get("dispatch_id") is not None and dispatch_id == row["dispatch_id"]
            if not same_dispatch_decline:
                logger.info(f"Rider {rider_id} already inflight for order {order_number}")
                return outcome(ALREADY_ON_THIS_JOB, row["order_number"])
            logger.info(f"Rider {rider_id} declining inflight dispatch {dispatch_id} for order {order_number}; cancel flow")
        else:
            logger.info(f"Order {order_number} already inflight with rider {row['rider_id']} (tapped by {rider_id})")
            return outcome(TAKEN)

    now = datetime.now().isoformat()
    if not accept:
        touched = await asyncio.to_thread(
            lambda: client_ordelo.table("delivery_dispatch")
            .update({"status_update_dtts": now})
            .eq("dispatch_id", dispatch_id)
            .eq("status", "assigned")
            .execute()
        )
        if touched.data:
            from ordelo.agents.agent_runner import run_rider_agent_w_custom_msg  # local: the runner is heavy

            logger.info(f"Assigned dispatch {dispatch_id} declined by rider {rider_id}; triggering cancel flow")
            await run_rider_agent_w_custom_msg(
                recipient=rider_id,
                dispatch_id=dispatch_id,
                system_msg="call `tool cancel_delivery_before_pickup`",
                human_msg=f"I need to cancel order {order_number} before pickup.",
            )
            return outcome(CANCEL_OWN_JOB)
        await asyncio.to_thread(
            lambda: client_ordelo.table("delivery_dispatch")
            .update({"status": "declined", "status_update_dtts": now})
            .eq("dispatch_id", dispatch_id)
            .in_("status", ["unassigned", "accepted"])
            .execute()
        )
        return outcome(DECLINED)

    status = summary[0]["status"]
    if status == "unassigned":
        # Every accepted offer is marked; job_assign_dispatch() (every 5 s) picks the winner.
        await asyncio.to_thread(
            lambda: client_ordelo.table("delivery_dispatch").update({"status": "accepted"}).eq("dispatch_id", dispatch_id).execute()
        )
        return outcome(ACCEPTED)
    if status in ("completed", "timedout"):
        logger.info(f"Delivery job already {status} for order number: {order_number}")
        return outcome(GONE)
    return outcome(IGNORED)


async def record_offer_ref(dispatch_id: int, ref: str | None) -> None:
    """Store where the offer message is (delivery_dispatch.channel_msg_ref), so a closed offer can be edited (D49)."""
    if not ref:
        return
    await asyncio.to_thread(
        lambda: client_ordelo.table("delivery_dispatch").update({"channel_msg_ref": ref}).eq("dispatch_id", dispatch_id).execute()
    )


async def close_open_offers(
    order_number: str,
    reason: str,
    *,
    statuses: Iterable[str] = ("unassigned",),
    winner_dispatch_id: int | None = None,
) -> int:
    """Edit the order's still-open TELEGRAM offers in place (D49); returns how many were edited.

    statuses: which offer rows count as still open (default: never answered). winner_dispatch_id: that offer is edited to
    'assigned' instead of `reason`. WhatsApp offers are not touched (no new WhatsApp text, as today).
    """
    from ordelo.rider_messaging import messenger_for
    from ordelo.rider_messaging.factory import _rider_row

    rows = await asyncio.to_thread(
        lambda: client_ordelo.table("delivery_dispatch")
        .select("dispatch_id, rider_id, status, channel, channel_msg_ref")
        .eq("order_number", order_number)
        .eq("channel", "telegram")
        .execute()
        .data
        or []
    )
    wanted = set(statuses)
    edited = 0
    for row in rows:
        is_winner = winner_dispatch_id is not None and row["dispatch_id"] == winner_dispatch_id
        if not row.get("channel_msg_ref") or not (is_winner or row["status"] in wanted):
            continue
        try:
            tcid = (await _rider_row(row["rider_id"])).get("tcid")
            await messenger_for(row["rider_id"], "telegram", tcid).offer_closed(
                row["channel_msg_ref"], order_number, "assigned" if is_winner else reason
            )
            edited += 1
        except Exception:
            logger.exception(f"Could not close Telegram offer {row['dispatch_id']} for {order_number}")
    return edited
