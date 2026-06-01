"""
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
    . payment_complete_path - FastAPI route handling payment completion webhooks
    . pay_at_restaurant - Logs pay-at-restaurant order data
"""

# %%
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from pydantic import BaseModel
from config import client_ordelo
from utils_common.order_management.food_order_pymodel import FoodOrder
from config.params import get_restaurant_webhook_url_async
import httpx
from utils_common.order_management.order_db_ops_new import OrderItem
from watomation.routers.takeaway_hooks import init_takeaway_summary

# from elai.agent_runner import run_elai_graph_with_custom_msg
from loguru import logger

# %% Define Dependancies and routes

router = APIRouter(tags=["payment-hooks"])


# %% supporting functions
async def handle_payment_complete(food_order: FoodOrder):
    """
    Handles the update of the payment status in the graph and notifies the restaurant.

    Args:
        food_order: The food order object

    Returns:
        dict: Success status
    """

    # Call the restaurant api to update the payment status
    rest_ref = food_order.order_number.split("-")[0]
    payment_complete_url = await get_restaurant_webhook_url_async(
        rest_ref, "order-payment-complete"
    )
    recipient = food_order.recipient
    thread_id = food_order.thread_id
    order_id = food_order.order_id

    # Make async HTTP request to restaurant webhook
    async with httpx.AsyncClient() as http_client:
        try:
            res = await http_client.post(
                url=f"{payment_complete_url}/{recipient}/{thread_id}",
                json=food_order.model_dump(),
            )
            res.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
            logger.info(
                f"Successfully notified restaurant {rest_ref} for order {order_id}"
            )
        except httpx.HTTPError as e:
            logger.error(
                f"Error during restaurant notification for order {order_id}: {e}"
            )

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


@router.post("/payment-complete")
async def payment_complete_path(request: Request, background_tasks: BackgroundTasks):
    """
    This is called by stripe success webhook
    """
    # Unpack request
    request_body: dict = await request.json()

    # update payment status to `requires_payment`, `requires_capture`
    order_id = request_body["data"]["object"]["metadata"]["orderID"]
    logger.info(f"order_id:{order_id} - PaymentComplete webhook from stripe called")

    # Update the payment status
    response = (
        client_ordelo.table("food_order")
        .update({"payment_status": "requires_capture"})
        .eq("order_id", order_id)
        .execute()
    )

    # Call the restaurant api to update the payment status
    # Prepare the payload
    food_order = FoodOrder(**response.data[0])

    background_tasks.add_task(handle_payment_complete, food_order)

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

    return {"success": "success"}


# %%


@router.post("/payment-complete-test/{order_id}")
async def payment_complete_test_path(
    order_id: str,
    background_tasks: BackgroundTasks,
):
    """Test endpoint that replays the full payment-complete flow for a given order_id."""
    logger.info(f"order_id:{order_id} - PaymentComplete test triggered")

    response = (
        client_ordelo.table("food_order")
        .update({"payment_status": "requires_capture"})
        .eq("order_id", order_id)
        .execute()
    )

    food_order = FoodOrder(**response.data[0])

    background_tasks.add_task(handle_payment_complete, food_order)

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

    return {"success": "success"}


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
