"""
Payment webhook handler module for Elai Agent
    . Processes payment webhook events from payment providers
    . Extracts payment status information from webhook payloads
    . Updates payment status in database with transaction status
    . Triggers graph updates to notify agent of payment verification
    . Implements FastAPI router endpoints for payment webhooks
    . Retrieves app state resources for database access
  Functions/Classes:
    . handle_payment_complete - Processes payment completion and updates order status
    . payment_complete_path - FastAPI route handling payment completion webhooks
"""

# %%
from fastapi import APIRouter, Request, BackgroundTasks
from config import client_ordelo
from utils_common.order_management.food_order_pymodel import FoodOrder
from config.params import get_restaurant_webhook_url_async
import httpx

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

    ## Call the restaurant api to update the payment status
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
                url=f"{payment_complete_url}{recipient}/{thread_id}",
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
    try:
        response = client_ordelo.rpc(
            "init_delivery", {"p_cust_id": recipient, "p_order_number": order_number}
        ).execute()
        logger.info(
            f"init_delivery completed for order {order_number} with response {response}"
        )
    except Exception as e:
        logger.error(f"init_delivery failed for order {order_number}: {e}")


# %%


@router.post("/payment-complete")
async def payment_complete_path(request: Request, background_tasks: BackgroundTasks):
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

    ## Call the restaurant api to update the payment status
    # Prepare the payload
    food_order = FoodOrder(**response.data[0])

    background_tasks.add_task(handle_payment_complete, food_order)

    background_tasks.add_task(
        init_delivery_summary, food_order.order_number, food_order.recipient
    )

    # Recipient not found.
    recipient = request_body["data"]["object"]["metadata"]["recipient"]

    return {"success": "success"}


# %%


@router.post("/payment-complete-test/{order_number}")
async def payment_complete_test_path(
    order_number: str,
    background_tasks: BackgroundTasks,
    recipient: str = "447448440754",
):
    # ELAS-KDDV-21 i want to highlight this example in the docstring
    # Add RPC call to background tasks to avoid blocking and timeout
    background_tasks.add_task(init_delivery_summary, order_number, recipient)
    return {"success": "success"}


# %%
@router.post("/payment-capture/{order_number}")
async def payment_capture_path(
    order_number: str,
    background_tasks: BackgroundTasks,
    recipient: str = "447448440754",
):
    # ELAS-KDDV-21 i want to highlight this example in the docstring
    # Add RPC call to background tasks to avoid blocking and timeout
    background_tasks.add_task(init_delivery_summary, order_number, recipient)
    return {"success": "success"}
