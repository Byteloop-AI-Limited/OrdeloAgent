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
from config import client

# from elai.agent_runner import run_elai_graph_with_custom_msg
from loguru import logger

# %% Define Dependancies and routes

router = APIRouter(tags=["payment-hooks"])


# %% supporting functions
async def handle_payment_complete(request_body: dict):
    """
    Handles the update of the payment status in the graph.

    Args:
        request_body: The request body from the payment webhook
        graph: the graph object
        pool: the database connection pool
    """
    # update payment status to `requires_payment`, `requires_capture`
    order_id = request_body["data"]["object"]["metadata"]["orderID"]
    logger.info(f"order_id:{order_id} - PaymentComplete webhook from stripe called")

    # Update the payment status
    response = (
        client.table("food_order")
        .update({"payment_status": "requires_capture"})
        .eq("order_id", order_id)
        .execute()
    )

    recipient = response.data[0]["recipient"]
    thread_id = response.data[0]["thread_id"]

    # logger.error(f"response:{response}")
    # # update graph state
    # config = {"configurable": {"thread_id": thread_id, "recipient": recipient}}
    # await graph.aupdate_state(
    #     config, {"is_payment_successful": True}, as_node="toolNode"
    # )

    # await run_elai_graph_with_custom_msg(
    #     recipient, system_msg="Verify if payment is complete"
    # )

    return {"success": "success"}


@router.post("/payment-complete")
async def payment_complete_path(request: Request, background_tasks: BackgroundTasks):
    # Unpack request
    logger.info(f"PaymentComplete webhook from stripe called")
    request_body: dict = await request.json()
    background_tasks.add_task(handle_payment_complete, request_body)
    return {"success": "success"}


# %%


def init_delivery_task(order_number: str, recipient: str):
    """Background task to initialize delivery via RPC call."""
    try:
        client.rpc(
            "init_delivery", {"p_cust_id": recipient, "p_order_number": order_number}
        ).execute()
        logger.info(f"init_delivery completed for order {order_number}")
    except Exception as e:
        logger.error(f"init_delivery failed for order {order_number}: {e}")


@router.post("/payment-complete-test/{order_number}")
async def payment_complete_test_path(
    order_number: str,
    background_tasks: BackgroundTasks,
    recipient: str = "447448440754",
):
    # Add RPC call to background tasks to avoid blocking and timeout
    background_tasks.add_task(init_delivery_task, order_number, recipient)
    return {"success": "success"}
