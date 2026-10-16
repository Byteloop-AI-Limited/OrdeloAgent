"""
Delivery-progress gate for admin-triggered rider actions
    . Answers one question: is this delivery still in progress, and has the
      rider already collected the food?
    . Reads delivery_inflight (is the order still being worked) and
      delivery_dispatch.status (has it been picked up) -- never graph state,
      which goes blind (NULL) once a thread is closed or deleted; see
      docs/get_latest_state_guide.md for why that path was rejected
    . Fails closed: any read error, or an inflight row missing its dispatch
      row, reports DeliveryProgress.UNKNOWN so callers block rather than act
      on unverified state
    . Guards against stale WhatsApp buttons: buttons never expire, so an old
      tap for a finished order must not act on the rider's current job
  Functions/Classes:
    . DeliveryProgress - The four possible answers; only AWAITING_PICKUP proceeds
    . GATE_REPLIES - Shared admin-facing reply text per DeliveryProgress value
    . check_delivery_progress - Resolves DeliveryProgress (+ the inflight row) for an order/rider

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . delivery_dispatch (table, ordelo_datamodels/dispatch/delivery_dispatch.sql): reads, named in code (passed to a query helper)
  . delivery_inflight (table, ordelo_datamodels/dispatch/delivery_inflight.sql): reads, named in code (passed to a query helper)
(end of database objects)
"""

# %%
import asyncio
from enum import StrEnum

from config import client_ordelo, logger

PICKED_UP_DISPATCH_STATUSES = ("pickedup", "completed")


class DeliveryProgress(StrEnum):
    NOT_IN_PROGRESS = "not_in_progress"  # no delivery_inflight row, or stale button for another job
    PICKED_UP = "picked_up"  # dispatch status is pickedup / completed
    AWAITING_PICKUP = "awaiting_pickup"  # the only state in which the caller should proceed
    UNKNOWN = "unknown"  # read failed or data inconsistent -> block


GATE_REPLIES: dict[DeliveryProgress, str] = {
    DeliveryProgress.NOT_IN_PROGRESS: "Invalid, this order is no longer in progress",
    DeliveryProgress.PICKED_UP: "Invalid, food already pickedup",
    DeliveryProgress.UNKNOWN: "Could not verify order status. Please retry.",
}


# %%
async def check_delivery_progress(
    *,
    order_number: str | None = None,
    rider_id: str | None = None,
) -> tuple[DeliveryProgress, dict | None]:
    """Resolves whether a delivery is still in progress and not yet picked up.

    Callers key by whichever identifier their callback carries:
      - order_number alone (e.g. admin_adjust_pickup_time, restaurant-triggered
        pickup-time-adjusted): looks up delivery_inflight by order_number directly.
      - rider_id alone, or rider_id + order_number (e.g. admin_collection_ready,
        the notify-food-ready-for-pickup webhook): looks up delivery_inflight by
        rider_id. When order_number is also supplied, a mismatch against the
        inflight row's order_number is treated as a stale button for a
        different (now-finished) job and reported as NOT_IN_PROGRESS, even
        though the rider does have *some* delivery inflight.

    Returns (DeliveryProgress.UNKNOWN, None) on any read failure, on an
    inflight row with no matching delivery_dispatch row, or when neither
    order_number nor rider_id is supplied -- all three block the caller
    rather than letting a stale or unverifiable action through. The last
    case is a caller bug (e.g. a callback missing an expected field), so it
    is reported as UNKNOWN rather than silently querying on NULL and reading
    back NOT_IN_PROGRESS, which would be indistinguishable from a genuinely
    finished order.
    """
    if order_number is None and rider_id is None:
        logger.error("check_delivery_progress called with neither order_number nor rider_id")
        return DeliveryProgress.UNKNOWN, None

    try:
        if order_number is not None:
            inflight = await asyncio.to_thread(
                lambda: (
                    client_ordelo.table("delivery_inflight")
                    .select("dispatch_id, order_number, rider_id")
                    .eq("order_number", order_number)
                    .execute()
                )
            )
        else:
            inflight = await asyncio.to_thread(
                lambda: (
                    client_ordelo.table("delivery_inflight")
                    .select("dispatch_id, order_number, rider_id")
                    .eq("rider_id", rider_id)
                    .execute()
                )
            )
    except Exception as e:
        logger.error(
            f"Failed to read delivery_inflight for order_number={order_number} "
            f"rider_id={rider_id}: {e}"
        )
        return DeliveryProgress.UNKNOWN, None

    if not inflight.data:
        return DeliveryProgress.NOT_IN_PROGRESS, None

    row = inflight.data[0]

    # Stale cross-order button: rider is inflight, but on a different job.
    if order_number is not None and row.get("order_number") != order_number:
        return DeliveryProgress.NOT_IN_PROGRESS, None

    dispatch_id = row.get("dispatch_id")

    try:
        dispatch = await asyncio.to_thread(
            lambda: (
                client_ordelo.table("delivery_dispatch")
                .select("status")
                .eq("dispatch_id", dispatch_id)
                .execute()
            )
        )
    except Exception as e:
        logger.error(f"Failed to read delivery_dispatch for dispatch_id={dispatch_id}: {e}")
        return DeliveryProgress.UNKNOWN, row

    if not dispatch.data:
        logger.error(
            f"delivery_inflight row for dispatch_id={dispatch_id} has no matching "
            "delivery_dispatch row"
        )
        return DeliveryProgress.UNKNOWN, row

    status = dispatch.data[0].get("status")
    if status in PICKED_UP_DISPATCH_STATUSES:
        return DeliveryProgress.PICKED_UP, row

    return DeliveryProgress.AWAITING_PICKUP, row
