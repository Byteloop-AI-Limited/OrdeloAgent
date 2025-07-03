"""
Delivery webhook handlers for Ordelo delivery system
    . Processes delivery-related webhook events from database triggers
    . Manages delivery dispatch assignments and inflight tracking
    . Implements function chaining pattern for complex workflows
    . Handles missed dispatch notifications and rider communications
    . Provides FastAPI endpoints for delivery operations
    . Uses PostgreSQL CTEs for conditional database operations
    . Follows webhook pattern where database triggers call FastAPI endpoints
    . Handles empty payloads gracefully in endpoints
  Functions/Classes:
    . get_payload - Helper to parse webhook payloads
    . wa_send_delivery_dispatch_request_to_rider - Notifies riders via WhatsApp
    . post_rider_event_inflight - Posts delivery summary to webhook
    . post_delivery_timedout - Posts delivery timeout information
    . delivery_hook_root - Root endpoint for delivery hooks
    . delivery_dispatch_hook - Processes dispatch assignments
    . delivery_inflight_graph_init_hook - Initializes inflight tracking
    . notify_missed_dispatches_hook - Handles missed dispatch cases
    . notify_food_ready_for_pickup - Notifies rider about food readiness
    . delivery_timedout - Handles delivery timeout events
    . check_rider_allocation_status - Checks rider allocation status
"""

from fastapi import APIRouter, Request, Depends, BackgroundTasks
from ordelo_datamodels.delivery_pymodels import DeliveryDetail
from config import logger, _async_wa_client, pg_settings
from pywa.types import Button
from pywa_async import WhatsApp
from datetime import datetime, timedelta
import json
from psycopg_pool import AsyncConnectionPool
from ordelo.agents.agent_runner import init_ordelo_graph
import asyncio
from config import client_ordelo, get_webhook_url
import httpx
from ordelo.agents.agent_runner import run_rider_graph


# %% Define Dependancies and routes
async def get_payload(request: Request):
    return await request.json()


client = pg_settings.client

router = APIRouter(tags=["delivery_hooks"])


# %% supporting functions
async def wa_send_delivery_dispatch_request_to_rider(
    recipient: str,
    delivery_summary: dict,
    dispatch_id: int,
    _async_wa_client: WhatsApp = _async_wa_client,
):
    """
    Sends a delivery dispatch request to a rider via WhatsApp.

    This function prepares the payload for a rider to accept or decline a delivery dispatch.
    It creates JSON payloads for both accept and decline responses that will be used in
    interactive buttons sent to the rider.

    Args:
        recipient (str): The WhatsApp phone number of the rider to receive the dispatch
        delivery_detail (DeliveryDetail): Details of the delivery order
        dispatch_id (int): Unique identifier for this dispatch request
        _async_wa_client (WhatsApp, optional): WhatsApp client instance for sending messages
    """
    order_number = delivery_summary["order_number"]

    accept_pl = {
        "command": "/dispatchResponse",
        "order_number": order_number,
        "dispatch_id": dispatch_id,
        "status": "accepted",
        "rider_id": recipient,
    }

    decline_pl = {
        "command": "/dispatchResponse",
        "order_number": order_number,
        "dispatch_id": dispatch_id,
        "status": "declined",
        "rider_id": recipient,
    }
    pickup_time = (datetime.now() + timedelta(minutes=25)).strftime("%I:%M %p")

    header_text = f"{delivery_summary['distance']} miles, £{delivery_summary['rider_payout']}, @{pickup_time}"
    wa_text = f"""
    Pickup time - *{pickup_time}*

Pickup location - *{delivery_summary["rest_name"]}*
{delivery_summary["rest_address"]}

Drop off location - *{delivery_summary["customer_name"]}*
{delivery_summary["customer_address"]}

Order number - *{delivery_summary["order_number"]}*

Vehicle type - *{delivery_summary["vehicle_type"]}*
    """
    await _async_wa_client.send_message(
        to=recipient,
        # reply_to_message_id=msg.id,
        header=header_text,
        text=wa_text,
        footer="⚡Ordelo",
        buttons=[
            Button(title="Accept", callback_data=json.dumps(accept_pl)),
            Button(title="Decline", callback_data=json.dumps(decline_pl)),
        ],
    )


# %% post rider event inflight
async def post_rider_event_inflight(delivery_detail: DeliveryDetail):
    """
    Posts the delivery summary for a given order_number to the rider-inflight webhook.

    Args:
        order_number (str): The unique identifier for the order.

    Side Effects:
        Sends an HTTP POST request to the configured rider-inflight webhook endpoint
        with the all delivery details as JSON payload and prints the response status and JSON.
    """
    delivery_summary: dict = (
        client_ordelo.table("delivery_summary")
        .select("*")
        .eq("order_number", delivery_detail.order_number)
        .limit(1)
        .execute()
        .data[0]
    )
    rider_master = (
        client_ordelo.table("rider_master")
        .select("rider_name", "rider_id")
        .eq("rider_id", delivery_detail.rider_id)
        .eq("vehicle_type", delivery_detail.vehicle_type)
        .limit(1)
        .execute()
        .data[0]
    )
    payload = {
        "delivery_summary": delivery_summary,
        "delivery_detail": delivery_detail.model_dump(),
        "rider_master": rider_master,
    }
    rest_ref = delivery_detail.order_number.split("-")[0]
    async with httpx.AsyncClient() as client:
        response = await client.post(
            get_webhook_url(rest_ref, "rider-inflight"),
            json=payload,
        )
        logger.info("Restaurant notified of rider")
        logger.info("Status code:", response.status_code)


# %% post delivery timedout
async def post_delivery_timedout(delivery_summary: dict):
    """
    Posts the delivery summary for a given order_number to the delivery-timedout webhook.

    Args:
        delivery_summary (dict): The payload for the delivery-timedout webhook.

    Side Effects:
        Sends an HTTP POST request to the configured delivery-timedout webhook endpoint
        with the all delivery details as JSON payload and prints the response status and JSON.
    """
    rest_ref = delivery_summary["order_number"].split("-")[0]
    async with httpx.AsyncClient() as client:
        response = await client.post(
            get_webhook_url(rest_ref, "delivery-timedout"),
            json=delivery_summary,
        )
    logger.info("Restaurant notified of delivery timeout")
    logger.info("Status code:", response.status_code)


# %% Define paths
@router.get(
    "/",
    summary="Root Endpoint",
    description="Returns a simple message to verify the delivery hooks router is working",
    response_description="A welcome message",
    responses={
        200: {
            "description": "Successfully retrieved welcome message",
            "content": {
                "application/json": {"example": {"message": "Delivery Hooks Router"}}
            },
        }
    },
)
async def delivery_hook_root():
    return {"message": "Delivery Hooks Router"}


@router.post(
    "/delivery-dispatch",
    summary="Process Delivery Dispatch",
    description="""
    Processes a new delivery dispatch request and notifies the assigned rider.
    
    This endpoint:
    1. Receives delivery dispatch and detail information
    2. Validates the payload contains required information
    3. Sends a WhatsApp notification to the assigned rider for job acceptance
    """,
    response_description="Status of the dispatch operation and the processed data",
    responses={
        200: {
            "description": "Successfully processed dispatch request",
            "content": {
                "application/json": {
                    "example": {
                        "status": "success",
                    }
                }
            },
        }
    },
)
async def delivery_dispatch_hook(
    background_tasks: BackgroundTasks,
    payload: dict = Depends(get_payload),
):
    """
    Handles incoming delivery dispatch webhook payloads and schedules sending dispatch requests to riders as background tasks.
        . Accepts payload with bulk_dispatch list
        . Schedules wa_send_delivery_dispatch_request_to_rider for each dispatch using BackgroundTasks
        . Returns immediately with status success if no dispatches
    Functions/Classes
        . delivery_dispatch_hook
        . wa_send_delivery_dispatch_request_to_rider
    Key Functions:
        . delivery_dispatch_hook - schedules dispatch sends in background
    """
    dispatches = payload.get("bulk_dispatch") or []
    if not dispatches:
        return {"status": "success"}

    for d in dispatches:
        background_tasks.add_task(
            wa_send_delivery_dispatch_request_to_rider,
            recipient=d["rider_id"],
            delivery_summary=d,
            dispatch_id=d["dispatch_id"],
        )
        logger.info(f"Enqueued dispatch for rider {d['rider_id']}")
    return {"status": "success"}


# %% Delivery Inflight Graph Init; Fix this
@router.post(
    "/delivery-inflight-graph-init",
    summary="Initialize Delivery Inflight Graph",
    description="""
    Processes a new delivery inflight record and initializes the delivery tracking graph.
    
    This endpoint:
    1. Receives delivery inflight and detail information
    2. Validates the payload contains required information
    3. Initializes the delivery tracking graph for the inflight delivery
    """,
    response_description="Status of the graph initialization operation and the processed data",
    responses={
        200: {
            "description": "Successfully initialized delivery tracking graph",
            "content": {
                "application/json": {
                    "example": {
                        "status": "success",
                        "data": {
                            "delivery_inflight": [
                                {
                                    "dispatch_id": "123",
                                    "rider_id": "456",
                                    "order_number": "789",
                                }
                            ],
                            "delivery_detail": [
                                {"order_number": "789", "customer_name": "John Doe"}
                            ],
                        },
                    }
                }
            },
        }
    },
)
async def delivery_inflight_graph_init_hook(
    background_tasks: BackgroundTasks,
    payload: dict = Depends(get_payload),
):
    """
    On insert into delivery_inflight table, trigger delivery inflight graph initialization webhook.

    This endpoint processes a delivery inflight record by extracting
    rider ID, dispatch ID, order number, and delivery details from the request payload.
    It then schedules background tasks for initializing the delivery tracking graph and calling the restaurant webhook.

    Args:
        background_tasks (BackgroundTasks): FastAPI background task manager
        payload (dict): The HTTP request payload containing delivery details

    Returns:
        dict: A dictionary with the status of the operation and the original payload data.
    """
    # Validate payload
    if "delivery_detail" not in payload or len(payload["delivery_detail"]) == 0:
        logger.error("No delivery_detail found: from inflight hook")
        return {"status": "error", "data": payload}

    # Extract data from payload
    delivery_detail = DeliveryDetail(**payload["delivery_detail"][0])

    # 1. Call restaurant webhook - rider-inflight-event (background)
    if "test" not in delivery_detail.order_number.lower():
        background_tasks.add_task(post_rider_event_inflight, delivery_detail)

    # 2. Initialize ordelo graph as background task
    background_tasks.add_task(init_ordelo_graph, delivery_detail)

    logger.info(
        f"Enqueued inflight graph init for order number: {delivery_detail.order_number}"
    )

    return {"status": "success"}


# %% Notify missed dispatches
@router.post(
    "/notify-missed-dispatches",
    summary="Notify Missed Dispatches",
    description="""
    Notifies riders about missed dispatches.
    
    This endpoint:
    1. Receives order_number and a list of rider IDs
    2. Sends a notification to each rider (logger.info)
    3. Uses sbase_update(table='delivery_dispatch', {"status": "missed"}, order_number=order_number)
    """,
    response_description="Status of the notification operation and the processed data",
    responses={
        200: {
            "description": "Successfully notified about missed dispatches",
            "content": {
                "application/json": {
                    "example": {
                        "status": "success",
                        "data": {
                            "order_numbers": ["ORD123", "ORD456"],
                            "updated_dispatch_count": 5,
                        },
                    }
                }
            },
        }
    },
)
async def notify_missed_dispatches_hook(
    background_tasks: BackgroundTasks,
    payload: dict = Depends(get_payload),
):
    """
    Process missed dispatches notification.

    This endpoint receives information about dispatches that have timed out
    and updates their status to 'missed' in the database. It also logs
    notifications that would be sent to riders. Message sends are scheduled as background tasks.

    Args:
        background_tasks (BackgroundTasks): FastAPI background task manager
        payload (dict): The HTTP request payload containing missed dispatches

    Returns:
        dict: A dictionary with the status of the operation and summary data.
    """
    # Handle empty or missing missed_dispatches
    if "missed_dispatches" not in payload or not payload["missed_dispatches"]:
        logger.info("No missed_dispatches data found in payload, nothing to process")
        return {
            "status": "success",
            "message": "No missed dispatches to process",
            "data": {"order_numbers": [], "updated_dispatch_count": 0},
        }

    order_numbers = []

    # Process each order with missed dispatches
    for missed_dispatch in payload["missed_dispatches"]:
        logger.info(f"notify_missed_dispatches_hook received: {missed_dispatch}")

        order_number = missed_dispatch["order_number"]
        order_numbers.append(order_number)

        dispatches_to_be_updated_as_missed = []

        # Schedule notification to each rider as a background task
        for dispatch in missed_dispatch["dispatches"]:
            rider_id = dispatch["rider_id"]
            dispatch_id = dispatch["dispatch_id"]
            dispatches_to_be_updated_as_missed.append(dispatch_id)

            _text = f"""
            Sorry, the order was picked up by another rider. Order number: *{order_number}*
            """

            # Send notification to rider in background
            background_tasks.add_task(
                _async_wa_client.send_message, to=rider_id, text=_text
            )

        # Mark dispatches as missed, they will not be pickup by notify_missed_dispatches sql function again
        response = (
            client.table("delivery_dispatch")
            .update({"status": "missed"})
            .in_("dispatch_id", dispatches_to_be_updated_as_missed)
            .execute()
        )

        logger.success(f"Marked dispatches as missed for order {response}")

    return {"status": "success"}


# %% Notify food ready for pickup
@router.post(
    "/notify-food-ready-for-pickup/{recipient}",
    summary="Notify food ready for pickup. Initiated by restaurant admin agent",
    response_description="Status of the notification operation",
)
async def notify_food_ready_for_pickup(
    recipient: str,
    background_tasks: BackgroundTasks,
    payload: dict = Depends(get_payload),
):
    """
    Notify food ready for pickup to a specific rider. Schedules notification as a background task.

    Args:
        recipient (str): The WhatsApp phone number or unique identifier of the rider.
        background_tasks (BackgroundTasks): FastAPI background task manager
        payload (dict): The JSON payload sent in the POST request body.

    Returns:
        dict: Status of the notification operation.
    """
    restaurant_name = payload.get("restaurant_name", None)

    background_tasks.add_task(
        run_rider_graph,
        recipient,
        system_msg=f"call `tool notify_food_ready_for_pickup`. Rider should hurry to {restaurant_name} to pickup the food.",
    )
    return {"status": "success", "recipient": recipient, "payload": payload}


# %% delivery-timedout
@router.post(
    "/delivery-timedout",
    summary="Handle delivery timedout. Called by scheduled job `process_delivery` when status of `delivery_summary` changes to 'timedout'.",
    response_description="Status of the delivery timedout operation",
)
async def delivery_timedout(
    background_tasks: BackgroundTasks,
    payload: dict = Depends(get_payload),
):
    """
    Handle delivery timedout event. Schedules post_delivery_timedout as a background task.

    Args:
        background_tasks (BackgroundTasks): FastAPI background task manager
        payload (dict): The JSON payload sent in the POST request body.

    Returns:
        dict: Status of the delivery timedout operation.
    """
    logger.info(f"delivery_timedout received: {payload}")
    delivery_summary_lst = payload.get("delivery_summary", None)
    delivery_summary = delivery_summary_lst[0]
    if "test" not in delivery_summary["order_number"].lower():  # skip test orders
        background_tasks.add_task(post_delivery_timedout, delivery_summary)
    return {"status": "success"}


# %% Check rider allocation status
@router.get(
    "/check-rider-allocation-status/{order_number}",
    summary="Check rider allocation status",
    response_description="Status of the rider allocation status operation",
)
async def check_rider_allocation_status(
    order_number: str,
):
    delivery_summary = (
        client.table("delivery_summary")
        .select("*")
        .eq("order_number", order_number)
        .limit(1)
        .execute()
        .data[0]
    )
    return {"delivery_summary_status": delivery_summary["status"]}
