"""
R3: web-origin isolation and customer tracking safeguards.

Payment webhook handler module for Elai Agent
    . Processes payment webhook events from payment providers
    . Extracts payment status information from webhook payloads
    . Updates payment status in database with transaction status
    . Triggers graph updates to notify agent of payment verification
    . Implements FastAPI router endpoints for payment webhooks
    . Retrieves app state resources for database access
    . Accepts pay-at-restaurant requests and logs order data
  Functions/Classes:
    . PayAtRest - Pydantic model for pay-at-restaurant requests
    . handle_payment_complete - Processes payment completion and updates order status
    . payment_complete_path - Stripe payment-complete webhook (M2 inbox, always
      on since R3.1; web orders skip the restaurant app, ADR-0003)
    . init_reconciler_path - Alert-only target of job_payment_init_reconciler()
    . pay_at_restaurant - Logs pay-at-restaurant order data
    . Routes customer notifications through the R1b notifier (always on since R3.1)
"""

from utils_common.notify import customer_notifier
from utils_common.notify.customer_notifier import CustomerOrderEvent

# %%
from typing import List, Optional


from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from pydantic import BaseModel
from config import client_ordelo
from config.params import get_wa_logger
from utils_common.payment_ms.payment_events import (
    REJECTED_STATE,
    UNKNOWN_ORDER,
    parse_payment_complete,
    record_payment_authorised,
)
from utils_common.order_management.food_order_pymodel import FoodOrder
from utils_common.order_management.order_db_ops_new import OrderItem
from watomation.routers.takeaway_hooks import init_takeaway_summary

# from elai.agent_runner import run_elai_graph_with_custom_msg
from loguru import logger

# %% Define Dependancies and routes

router = APIRouter(tags=["payment-hooks"])


# %% supporting functions
async def handle_payment_complete(food_order: FoodOrder):
    """
    Publishes the payment_authorised customer event. The notifier routes it to
    the restaurant app for WhatsApp orders and to the order page for web
    orders, which never reach a restaurant app (ADR-0003 / D27).

    Args:
        food_order: The food order object

    Returns:
        dict: Success status
    """

    await customer_notifier.publish(food_order.order_number, CustomerOrderEvent(
        "payment_authorised", "payment_authorised", "order-payment-complete",
        food_order.model_dump(), f"/{food_order.recipient}/{food_order.thread_id}"))
    return {"success": "success"}


# %%


def init_delivery_summary(order_number: str, recipient: str):
    """Background task to initialize delivery via RPC call."""
    from config.params import _resolve_rest_ref

    try:
        rest_ref = order_number.split("-")[0]
        rest_ref = _resolve_rest_ref(rest_ref)
        response = client_ordelo.rpc(
            "init_delivery",
            {
                "p_cust_id": recipient,
                "p_order_number": order_number,
                "p_rest_ref": rest_ref,
            },
        ).execute()
        logger.info(
            f"init_delivery completed for order {order_number} with response {response}"
        )
    except Exception as e:
        logger.error(f"init_delivery failed for order {order_number}: {e}")


# %%


async def _schedule_after_authorisation(
    order_row: dict, background_tasks: BackgroundTasks
) -> FoodOrder:
    """Queue the payment_authorised customer event and summary init."""
    food_order = FoodOrder(**order_row)
    background_tasks.add_task(handle_payment_complete, food_order)

    if order_row.get("origin_channel") == "web":
        from utils_common.web_ordering.common import query
        background_tasks.add_task(query, "UPDATE thread SET is_active=false WHERE thread_id=%s AND agent='WEB'", (food_order.thread_id,))
    if food_order.action == "delivery":
        background_tasks.add_task(
            init_delivery_summary, food_order.order_number, food_order.recipient
        )
    elif food_order.action == "takeaway":
        background_tasks.add_task(
            init_takeaway_summary, food_order.order_number, food_order.recipient
        )
    else:
        logger.warning(
            f"Unknown food_order.action={food_order.action} for order={food_order.order_number}; summary init skipped"
        )
    return food_order


async def _apply_via_inbox(body: dict, background_tasks: BackgroundTasks) -> dict:
    """Plan M2: apply a payment-complete body at most once. Always answers 200."""
    try:
        evt = parse_payment_complete(body)
    except ValueError as err:
        logger.error(f"payment-complete: {err}")
        return {"success": "success", "outcome": "invalid"}
    if evt is None:
        logger.info(f"payment-complete: ignored event type {body.get('type')!r}")
        return {"success": "success", "outcome": "ignored"}

    from utils_common.web_ordering.lifecycle import reject_late
    late = await reject_late(evt)
    if late:
        return {"success": "success", "outcome": late}
    outcome = await record_payment_authorised(evt)
    if outcome.applied and outcome.order:
        await _schedule_after_authorisation(outcome.order, background_tasks)
    elif outcome.outcome == REJECTED_STATE:
        logger.warning(
            f"payment-complete: order {evt.order_id} is {outcome.payment_status}, "
            f"event {evt.provider_event_id} not applied"
        )
    elif outcome.outcome == UNKNOWN_ORDER:
        logger.error(f"payment-complete: unknown order {evt.order_id}")
    return {"success": "success", "outcome": outcome.outcome}


@router.post("/payment-complete")
async def payment_complete_path(request: Request, background_tasks: BackgroundTasks):
    """
    Called by Stripe (checkout.session.completed), unsigned (D23).

    The event is applied at most once through the payment inbox (plan M2).
    Web orders skip the restaurant app (D27).
    """
    request_body: dict = await request.json()
    return await _apply_via_inbox(request_body, background_tasks)


# %%


class InitReconcilerOrder(BaseModel):
    order_id: str
    order_number: str
    action: Optional[str] = None
    authorised_at: Optional[str] = None


class InitReconcilerRequest(BaseModel):
    orders: List[InitReconcilerOrder]


async def _alert_init_missing(orders: List[InitReconcilerOrder]) -> None:
    lines = [f"- {o.order_number} ({o.action or '?'}), paid {o.authorised_at or '?'}" for o in orders]
    message = (
        "Payment authorised but no fulfilment summary after 2 min "
        "(init reconciler, alert-only):\n" + "\n".join(lines)
    )
    try:
        wa_logger = await get_wa_logger()
        await wa_logger.info(message)
    except Exception as err:  # noqa: BLE001 - alerting must not fail the job
        logger.error(f"init reconciler: overwatch alert failed: {err}")
    logger.warning(message)


@router.post("/init-reconciler")
async def init_reconciler_path(
    request: InitReconcilerRequest, background_tasks: BackgroundTasks
):
    """Called by job_payment_init_reconciler(); alerts overwatch (alert-only mode)."""
    if request.orders:
        background_tasks.add_task(_alert_init_missing, request.orders)
    return {"alerted": len(request.orders)}


# %%


class PayAtRest(BaseModel):
    """Request model for pay-at-restaurant orders."""

    recipient: str
    thread_id: str
    order_id: str
    order_items: List[OrderItem]
    order_type: str
    notes: Optional[str] = None


@router.post(
    "/pay-at-restaurant/{rest_ref}",
    summary="Log a pay-at-restaurant order",
    description="""
    Accepts a pay-at-restaurant order payload and logs the data.
    """,
)
async def pay_at_restaurant(
    rest_ref: str,
    request: PayAtRest,
    background_tasks: BackgroundTasks,
):
    """
    This is called by checkout page on the restaurant frontend.

    Args:
        rest_ref: Restaurant reference code
        request: PayAtRest request with recipient, thread_id, order_number, and order_items

    Returns:
        Dict with success status
    """
    order_id = request.order_id
    order_type = request.order_type
    if order_type != "takeaway":
        raise HTTPException(status_code=400, detail="Invalid action")

    # Update the payment status
    response = (
        client_ordelo.table("food_order")
        .update({"payment_status": "pay_at_rest"})
        .eq("order_number", order_id)
        .execute()
    )

    # Call the restaurant api to update the payment status
    if not response.data:
        raise HTTPException(status_code=404, detail="Food order not found")
    food_order = FoodOrder(**response.data[0])

    # Call the restaurant agent to acknowledge the payment; Should I have a handle_pay_at_restaurant ?; Create according webhook
    background_tasks.add_task(handle_payment_complete, food_order)

    # Initialize the takeaway process with restaurant, to obtain a pickup_time
    order_number = food_order.order_number
    background_tasks.add_task(init_takeaway_summary, order_number, food_order.recipient)

    return {"status": "success", "order_number": order_number}


# %%
# @router.post("/payment-capture/{order_number}")
# async def payment_capture_path(
#     order_number: str,
#     background_tasks: BackgroundTasks,
#     recipient: str = "447448440754",
#     action: str = "delivery",
# ):
#     # ELAS-KDDV-21 i want to highlight this example in the docstring
#     # Add RPC call to background tasks to avoid blocking and timeout
#     if action == "takeaway":
#         background_tasks.add_task(init_takeaway_summary, order_number, recipient)
#     else:
#         background_tasks.add_task(init_delivery_summary, order_number, recipient)
#     return {"success": "success"}
