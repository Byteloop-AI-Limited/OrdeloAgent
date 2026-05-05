"""
Delivery webhook handlers for Ordelo delivery system
    . Processes delivery-related webhook events from database triggers
    . Manages delivery dispatch assignments and inflight tracking
    . Cancels payments for timed out deliveries via the payment microservice
    . Implements function chaining pattern for complex workflows
    . Handles missed dispatch notifications and rider communications
    . Provides FastAPI endpoints for delivery operations
    . Uses PostgreSQL CTEs for conditional database operations
    . Follows webhook pattern where database triggers call FastAPI endpoints
    . Handles empty payloads gracefully in endpoints
    . Manages thread lifecycle including automatic closure for inactive threads
    . Implements restaurant confirmation touchpoint before rider dispatch
    . Uses module-level WhatsApp client for confirmation workflow
    . Uses DeliverySummaryData, RestaurantMasterData, FoodOrder and OrderItem Pydantic models for restaurant confirmation payload
    . Trigger fires on restaurant_confirmation_status changes (not status)
  Functions/Classes:
    . DeliverySummaryData - Pydantic model for delivery_summary table fields (includes restaurant_confirmation_status, restaurant_msg_id, rider_msg_id, customer_msg_id)
    . RestaurantMasterData - Pydantic model for restaurant_master table fields
    . RestaurantConfirmationPayload - Pydantic model for restaurant confirmation webhook with trigger_reason
    . get_payload - Helper to parse webhook payloads
    . cancel_payment - Cancels payment for an order via payment microservice
    . wa_send_delivery_dispatch_request_to_rider - Notifies riders via WhatsApp
    . post_rider_event_inflight - Posts delivery summary to webhook (accepts DeliverySummary param)
    . post_delivery_timedout - Posts delivery timeout information
    . delivery_hook_root - Root endpoint for delivery hooks
    . delivery_dispatch_hook - Processes dispatch assignments
    . delivery_inflight_graph_init_hook - Initializes inflight tracking
    . notify_missed_dispatches_hook - Handles missed dispatch cases
    . notify_food_ready_for_pickup - Notifies rider about food readiness
    . delivery_timedout - Handles delivery timeout events
    . check_rider_allocation_status - Checks rider allocation status
    . shift_availability_enquiry_hook - Processes shift availability enquiries
    . admin_availability_enquiry_hook - Processes admin availability enquiries for restaurants
    . restaurant_confirmation_flow - Handles restaurant confirmation workflow (unconfirmed, accept, decline, timedout)
    . _handle_restaurant_unconfirmed - Sends order confirmation request to restaurant
    . _handle_restaurant_accept - Sends pickup time selection to restaurant
    . _handle_restaurant_decline - Updates status to unassigned on decline
    . _handle_restaurant_timedout - Logs restaurant confirmation timeout event
    . close_threads - Closes inactive threads and sends goodbye messages
"""

# %%
import asyncio
import json
from datetime import datetime, timedelta
from typing import List, Optional
from utils_common.tz_utils import UK_TZ, fmt_uk_time, parse_db_iso, to_uk_epoch
import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel
from pywa.types import Button
from pywa_async import WhatsApp
from config.params import get_restaurant_admins, get_wa_logger
from config import (
    _async_wa_client,
    client_ordelo,
    get_restaurant_webhook_url_async,
    logger,
    ms_settings,
    pg_settings,
)

# from ordelo.agent_app_handlers import enquire_shift_availability
from utils_common.waba_utils.wa_senders import (
    enquire_shift_availability,
    enquire_admin_availability,
)
from ordelo.agents.agent_runner import init_ordelo_graph, run_rider_agent_w_custom_msg
from ordelo_datamodels.delivery_pymodels import DeliverySummary
from utils_common.order_management.food_order_pymodel import FoodOrder
from utils_common.order_management.order_db_ops_new import OrderItem

from utils_common.waba_utils.wa_senders import (
    send_restaurant_order_confirmation,
    send_restaurant_pickup_time,
    admin_order_reciept,
)


# %% Define Dependancies and routes
async def get_payload(request: Request):
    return await request.json()


client = pg_settings.client

router = APIRouter(tags=["delivery_hooks"])


# %% Payload Models
class DeliverySummaryData(BaseModel):
    """Delivery summary fields from delivery_summary table."""

    order_number: str
    rest_id: str
    rest_name: str
    rest_lon: float
    rest_lat: float
    rest_address: str
    town: str
    customer_id: str
    customer_name: str
    customer_lon: float
    customer_lat: float
    customer_address: str
    restaurant_confirmation_status: str
    restaurant_update_dtts: Optional[str] = None
    restaurant_admin: Optional[str] = None
    status: str
    rest_confirmation_code: int
    cust_confirmation_code: int
    rest_prep_time_minutes: Optional[int] = None
    rest_confirmation_method: Optional[str] = None
    restaurant_msg_id: Optional[str] = None
    rider_msg_id: Optional[str] = None
    customer_msg_id: Optional[str] = None
    pickup_time: Optional[str] = None
    pickup_date: str
    rest_ref: Optional[str] = None
    dt: str
    dtts: str


class RestaurantMasterData(BaseModel):
    """Restaurant master fields from restaurant_master table."""

    rest_id: str
    rest_ref: str
    rest_name: str
    admins: List[str]
    lon: float
    lat: float
    house_number: Optional[str] = None
    building_name: Optional[str] = None
    street_name: Optional[str] = None
    city: Optional[str] = None
    postcode: Optional[str] = None


class RestaurantConfirmationPayload(BaseModel):
    """Payload model for restaurant confirmation webhook."""

    trigger_reason: str
    delivery_summary: DeliverySummaryData
    restaurant_master: RestaurantMasterData
    food_order: FoodOrder
    order_items: List[OrderItem]


# %%


async def capture_payment(order_number, restaurant_cc: int):
    """
    Captures a payment for the specified order using the payment microservice.

    Args:
        order_id (str): The ID of the order for which payment should be captured.

    Returns:
        str or None: The response text from the payment service if successful, otherwise None.
    """
    food_order = FoodOrder.from_order_number(order_number=order_number)
    if not food_order:
        logger.error(f"FoodOrder not found for order_id: {order_number}")
        return None

    order_id = food_order.order_id
    payment_uri = food_order.payment_uri

    # Call stripe
    async with httpx.AsyncClient() as _client:
        logger.info(
            f"Capturing payment for order {order_id} with payment URI: {payment_uri}"
        )
        try:
            capture_payload = await food_order.gen_capture_payload()
            capture_payload["restaurant_confirmation_code"] = str(restaurant_cc)
            logger.info(f"Capture payload: {capture_payload}")
            res = await _client.post(
                payment_uri,
                json=capture_payload,
                headers=ms_settings.stripe_headers,
            )
            res.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
            return res.text
        except httpx.HTTPError as e:
            logger.error(f"Error during payment capture for order {order_id}: {e}")
            if "res" in locals():
                logger.error(res.text)
            return None


# %%
async def cancel_payment(order_number):
    """
    Cancels a payment for the specified order using the payment microservice.

    Args:
        order_id (str): The ID of the order for which payment should be captured.

    Returns:
        str or None: The response text from the payment service if successful, otherwise None.
    """
    food_order = FoodOrder.from_order_number(order_number=order_number)
    if not food_order:
        logger.error(f"FoodOrder not found for order_id: {order_number}")
        return None

    order_id = food_order.order_id
    payment_uri = food_order.payment_uri
    cancel_payload = {
        "action": "delivery",
        "payment_mode": "cancel",
        "restRef": food_order.rest_ref,
    }

    # Call stripe
    async with httpx.AsyncClient() as _client:
        logger.info(
            f"Canceling payment for order {order_id} with payment URI: {payment_uri}"
        )

        try:
            res = await _client.post(
                payment_uri,
                json=cancel_payload,
                headers=ms_settings.stripe_headers,
            )
            res.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
            return res.text
        except httpx.HTTPError as e:
            logger.error(f"Error during payment cancellation for order {order_id}: {e}")
            if "res" in locals():
                logger.error(res.text)
            return None


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

    pickup_time = fmt_uk_time(delivery_summary["pickup_time"])

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
    logger.info(f"Sending dispatch to rider {recipient} for order {order_number}")
    await _async_wa_client.send_message(
        to=recipient,
        # reply_to_message_id=msg.id,
        header=header_text,
        text=wa_text,
        footer="♾️ Byteloop AI",
        buttons=[
            Button(title="Accept", callback_data=json.dumps(accept_pl)),
            Button(title="Decline", callback_data=json.dumps(decline_pl)),
        ],
    )


# %% notify overwatch
async def notify_overwatch(log_msg: str):
    wa_logger = await get_wa_logger()
    await wa_logger.info(log_msg)


# %% post rider event inflight
async def post_rider_event_inflight(delivery_summary: DeliverySummary):
    """
    Posts the delivery summary for a given order_number to the rider-inflight webhook.

    Args:
        delivery_summary (DeliverySummary): The delivery summary for the order.

    Side Effects:
        Sends an HTTP POST request to the configured rider-inflight webhook endpoint
        with the delivery summary as JSON payload and prints the response status and JSON.
    """

    payload = {
        "delivery_summary": delivery_summary.model_dump(mode="json"),
        # "delivery_detail": delivery_detail.model_dump(mode="json"),
    }
    rest_ref = delivery_summary.rest_ref
    webhook_url = await get_restaurant_webhook_url_async(rest_ref, "rider-inflight")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            webhook_url,
            json=payload,
        )
        logger.debug(
            f"Status code: {response.status_code}, Response: {response.json()}"
        )


# %% post delivery timedout
async def post_delivery_timedout(delivery_summary: dict):
    """
    Posts the delivery summary for a given order_number to the delivery-timedout webhook.

    Args:
        delivery_summary (dict): The payload for the delivery-timedout webhook.

    Side Effects:
        Sends an HTTP POST request to the configured delivery-timedout webhook endpoint
        with the delivery summary as JSON payload and prints the response status and JSON.
    """
    rest_ref = delivery_summary["order_number"].split("-")[0]
    webhook_url = await get_restaurant_webhook_url_async(rest_ref, "delivery-timedout")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            webhook_url,
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
    summary="Process Delivery Dispatch. Trigger: Insert into delivery_dispatch",
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
        . Skips dispatches for overwatch customers unless rider_id == customer_id
        . Returns immediately with status success if no dispatches
    Functions/Classes
        . delivery_dispatch_hook
        . wa_send_delivery_dispatch_request_to_rider
    Key Functions:
        . delivery_dispatch_hook - schedules dispatch sends in background
    """
    from config.params import get_overwatch_list

    dispatches = payload.get("bulk_dispatch") or []
    if not dispatches:
        return {"status": "success"}

    for d in dispatches:
        overwatch_list = get_overwatch_list()
        # Overwatch customers: block dispatches to other riders; allow only when rider == customer.
        if d["customer_id"] in overwatch_list:
            if d["rider_id"] == d["customer_id"]:
                background_tasks.add_task(
                    wa_send_delivery_dispatch_request_to_rider,
                    recipient=d["rider_id"],
                    delivery_summary=d,
                    dispatch_id=d["dispatch_id"],
                )
                logger.debug(
                    f"Overwatch dispatch for rider {d['rider_id']} for customer {d['customer_id']}"
                )
            logger.debug(
                f"Skipping dispatch for rider {d['rider_id']} for customer {d['customer_id']}"
            )
            continue
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
    summary="Initialize Delivery Inflight Graph. Trigger: Insert into delivery_inflight",
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
    # Validate payload and extract payload
    if "delivery_summary" not in payload or payload["delivery_summary"] is None:
        logger.error("No delivery_summary found: from inflight hook")
        return {"status": "error", "data": payload}

    dispatch_id = payload.get("delivery_inflight")[0].get("dispatch_id")
    if dispatch_id is None:
        raise ValueError("dispatch_id is required in delivery_inflight payload")

    delivery_summary = DeliverySummary(**payload["delivery_summary"])
    rest_confirmation_code = delivery_summary.rest_confirmation_code
    rider_master = payload.get("rider_master")

    # 1. Capture Stripe Payment - This also issues print job
    background_tasks.add_task(
        capture_payment, delivery_summary.order_number, rest_confirmation_code
    )

    # 2. Call restaurant webhook - rider-inflight-event (background)
    logger.info("step2: call restaurant webhook - rider-inflight-event")
    background_tasks.add_task(
        post_rider_event_inflight, delivery_summary=delivery_summary
    )

    # 3. Admin notification
    logger.info("step3: admin notification")
    background_tasks.add_task(
        admin_order_reciept,
        delivery_summary=delivery_summary,
        rider_master=rider_master,
    )

    # 4. Initialize ordelo graph as background task
    logger.info("step4: initialize ordelo graph")
    rider_name = (
        rider_master.get("rider_name", "Unknown") if rider_master else "Unknown"
    )
    rider_id = rider_master.get("rider_id", "Unknown") if rider_master else "Unknown"
    background_tasks.add_task(
        init_ordelo_graph,
        delivery_summary,
        rider_id=rider_id,
        rider_name=rider_name,
        dispatch_id=dispatch_id,
    )

    # 5. Notify overwatch
    logger.info("step5: notify overwatch")
    background_tasks.add_task(
        notify_overwatch,
        log_msg=f"{delivery_summary.order_number} is in flight for rider {rider_name}",
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
        run_rider_agent_w_custom_msg,
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
    rest_id = delivery_summary["rest_id"]

    # 1. Cancel payment
    try:
        await cancel_payment(order_number=delivery_summary["order_number"])
    except Exception:
        logger.exception(
            "Payment cancellation failed during delivery_timedout",
            extra={"order_number": delivery_summary.get("order_number")},
        )

    # 2. Notify restaurant admins
    rest_admins = get_restaurant_admins(rest_id=rest_id)

    for admin_phone in rest_admins:
        await _async_wa_client.send_message(
            to=admin_phone,
            text="No Rider Found for order number: " + delivery_summary["order_number"],
        )

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


@router.post(
    "/close-threads",
    summary="Close inactive threads. Called by job_close_thread() PostgreSQL function via Supabase cron",
    description="""
    Processes thread closure requests from the scheduled job_close_thread() function.
    
    Triggered by: Supabase cron job running every 5 minutes
    Source Function: job_close_thread() in ordelo_datamodels/jobs_n_functions/job_close_thread.sql
    
    Workflow:
    1. Receives JSON array of thread records to close
    2. For each thread:
       - Marks thread as inactive using ThreadHandler.make_threads_inactive()
       - Sends goodbye message to recipient via WhatsApp
    3. Returns success status with count of processed threads
    
    Payload Structure:
    [
        {
            "thread_id": "uuid",
            "recipient": "phone_number",
            "last_access_dtts": "timestamp",
            "is_active": boolean,
            "minutes_since_last_access": number
        }
    ]
    """,
)
async def close_threads(request: Request):
    pool = await pg_settings.get_pool()
    from utils_common.thread_management import ThreadHandler

    thread_handler = ThreadHandler(pool)
    try:
        payload = await request.json()
        print(f"Received close-threads payload: {payload}")

        # Loop through the records and close each thread
        if payload and isinstance(payload, list):
            for record in payload:
                await thread_handler.make_threads_inactive(
                    recipient=record["recipient"]
                )
                logger.info(f"Thread closed: {record}")
                await _async_wa_client.send_message(
                    to=record["recipient"],
                    text="Ending the converstaion, thank you and good bye 👋",
                )
        return {"status": "success", "processed_count": len(payload) if payload else 0}
    except Exception as e:
        logger.error(f"Error processing close-threads: {e}")
        return {"status": "error", "message": str(e)}


# %% Shift availability enquiry
@router.post(
    "/shift-availability-enquiry",
    summary="Handle shift availability enquiry. Called by enquire_shift_availability() PostgreSQL function",
    description="""
    Processes shift availability enquiry requests from the database.
    
    This endpoint:
    1. Receives a list of active riders from the PostgreSQL function
    2. Logs all rider IDs and rider names for monitoring
    3. Can be extended to perform additional operations with rider data
    """,
    response_description="Status of the shift availability enquiry operation",
    responses={
        200: {
            "description": "Successfully processed shift availability enquiry",
            "content": {
                "application/json": {
                    "example": {
                        "status": "success",
                        "riders_processed": 5,
                        "data": {
                            "event_type": "shift_availability_enquiry",
                            "riders": [
                                {"rider_id": "123", "rider_name": "John Doe"},
                                {"rider_id": "456", "rider_name": "Jane Smith"},
                            ],
                        },
                    }
                }
            },
        }
    },
)
async def shift_availability_enquiry_hook(
    payload: dict = Depends(get_payload),
    background_tasks: BackgroundTasks = None,
):
    """
    Handle shift availability enquiry webhook from PostgreSQL function.

    This endpoint processes the payload containing active riders and logs
    their information for monitoring and potential further processing.
    Uses background tasks to avoid DB timeout.

    Args:
        payload (dict): The JSON payload containing event_type, timestamp, and riders array
        background_tasks: FastAPI BackgroundTasks for async processing

    Returns:
        dict: Status of the operation and count of riders to be processed
    """
    logger.info(f"shift_availability_enquiry_hook received: {payload}")

    riders = payload.get("riders", [])
    event_type = payload.get("event_type", "unknown")
    rider_ids = [rider.get("rider_id") for rider in riders]

    update_shift_status = (
        client_ordelo.table("rider_master")
        .update({"is_in_shift": False, "shift_response_dtts": "now()"})
        .in_("rider_id", rider_ids)
        .execute()
    )

    if riders:
        logger.info(f"Scheduling {len(riders)} riders for {event_type} processing")
        background_tasks.add_task(_process_shift_availability, riders)
    else:
        logger.info("No active riders found in the enquiry")

    return {"status": "success", "riders_scheduled": len(riders)}


async def _process_shift_availability(riders: list):
    """Background task to process shift availability for riders."""
    for rider in riders:
        try:
            await enquire_shift_availability(
                wa=_async_wa_client,
                recipient=rider.get("rider_id"),
                name=rider.get("rider_name"),
            )
        except Exception as e:
            logger.error(f"Error processing shift availability for {rider}: {e}")


# %% Admin availability enquiry
@router.post(
    "/admin-availability-enquiry",
    summary="Handle admin availability enquiry. Called by enquire_admin_availability() PostgreSQL function",
    description="""
    Processes admin availability enquiry requests from the database.
    
    This endpoint:
    1. Receives a dict of restaurant admins from the PostgreSQL function
    2. For each restaurant, sends admin availability enquiry to each admin
    3. Logs processing status for monitoring
    """,
    response_description="Status of the admin availability enquiry operation",
    responses={
        200: {
            "description": "Successfully processed admin availability enquiry",
            "content": {
                "application/json": {
                    "example": {
                        "status": "success",
                        "admins_processed": 5,
                        "data": {
                            "event_type": "admin_availability_enquiry",
                            "restaurant_admins": {
                                "ELAS": ["447123456789", "447987654321"],
                                "ORDELO": ["447111222333"],
                            },
                        },
                    }
                }
            },
        }
    },
)
async def admin_availability_enquiry_hook(
    payload: dict = Depends(get_payload),
    background_tasks: BackgroundTasks = None,
):
    """
    Handle admin availability enquiry webhook from PostgreSQL function.

    This endpoint processes the payload containing restaurant admins and sends
    availability enquiry to each admin.
    Uses background tasks to avoid DB timeout.

    Args:
        payload (dict): The JSON payload containing event_type, timestamp, and restaurant_admins dict
        background_tasks: FastAPI BackgroundTasks for async processing

    Returns:
        dict: Status of the operation and count of admins to be processed
    """
    logger.info(f"admin_availability_enquiry_hook received: {payload}")

    restaurant_admins = payload.get("restaurant_admins", {})
    event_type = payload.get("event_type", "unknown")

    total_admins = sum(len(admins) for admins in restaurant_admins.values())

    if restaurant_admins:
        logger.info(
            f"Scheduling {len(restaurant_admins)} restaurants ({total_admins} admins) for {event_type} processing"
        )
        background_tasks.add_task(_process_admin_availability, restaurant_admins)
    else:
        logger.info("No restaurant admins found in the enquiry")

    return {"status": "success", "admins_scheduled": total_admins}


async def _process_admin_availability(restaurant_admins: dict):
    """Background task to process admin availability for restaurants."""
    for rest_ref, admins in restaurant_admins.items():
        logger.info(f"Processing {len(admins)} admins for restaurant {rest_ref}")
        for admin in admins:
            try:
                await enquire_admin_availability(recipient=admin)
            except Exception as e:
                logger.error(f"Error processing admin availability for {admin}: {e}")


# %%


async def _handle_restaurant_unconfirmed(
    delivery_summary: DeliverySummaryData,
    restaurant_master: RestaurantMasterData,
    food_order: FoodOrder,
    order_items: List[OrderItem],
) -> dict:
    """
    Handle restaurant_unconfirmed trigger: send order confirmation request to restaurant admin.

    Args:
        delivery_summary: Delivery summary data
        restaurant_master: Restaurant master data
        food_order: Food order data
        order_items: List of order items

    Returns:
        dict: Status response with order_number and recipient
    """
    # Build order items summary string
    order_items_str = ", ".join(
        [f"{item.quantity}x {item.product_name}" for item in order_items]
    )

    # Calculate total order amount
    order_amount = f"£{food_order.total_price:.2f}"

    order_time_epoch = to_uk_epoch(delivery_summary.dtts)

    # Send restaurant order confirmation to all admins
    admin_phones = restaurant_master.admins
    order_type = food_order.action
    for admin_phone in admin_phones:
        await send_restaurant_order_confirmation(
            recipient=admin_phone,
            order_number=food_order.order_number,
            order_amount=order_amount,
            order_items=order_items_str,
            order_time=order_time_epoch,
            order_type=order_type,
        )
        logger.info(
            f"Restaurant confirmation request sent for order {food_order.order_number} to {admin_phone}"
        )

    return {
        "status": "success",
        "action": "confirmation_sent",
        "order_number": food_order.order_number,
        "sent_to": admin_phones,
    }


async def _handle_restaurant_accept(
    delivery_summary: DeliverySummaryData,
    restaurant_master: RestaurantMasterData,
    food_order: FoodOrder,
    order_items: List[OrderItem],
) -> dict:
    """
    Handle restaurant_accept trigger: send pickup time selection to restaurant admin.

    Args:
        delivery_summary: Delivery summary data
        restaurant_master: Restaurant master data
        food_order: Food order data
        order_items: List of order items

    Returns:
        dict: Status response with order_number and recipient
    """

    # Build order items summary string
    order_items_str = ", ".join(
        [f"{item.quantity}x {item.product_name}" for item in order_items]
    )

    order_time_epoch = to_uk_epoch(delivery_summary.dtts)

    # Build header and text for pickup time message
    header = f"Order {food_order.order_number} - Pickup Time"
    text: str = f"Order accepted! Items: {order_items_str}\n\nPlease select estimated pickup time:"

    # Send pickup time selection
    for admin in restaurant_master.admins:
        await send_restaurant_pickup_time(
            recipient=admin,
            header=header,
            text=text,
            order_number=food_order.order_number,
            order_time_epoch=order_time_epoch,
            intervals_mins=[5, 15, 25],
        )

    return {
        "status": "success",
        "action": "pickup_time_sent",
        "order_number": food_order.order_number,
    }


async def _handle_restaurant_decline(
    delivery_summary: DeliverySummaryData,
    food_order: FoodOrder,
) -> dict:
    """
    Handle restaurant_decline trigger: update delivery_summary status to unassigned.

    Args:
        delivery_summary: Delivery summary data
        food_order: Food order data

    Returns:
        dict: Status response with order_number
    """
    # Update delivery_summary status to unassigned
    client.table("delivery_summary").update({"status": "unassigned"}).eq(
        "order_number", food_order.order_number
    ).execute()

    logger.info(
        f"Restaurant declined order {food_order.order_number}, status updated to unassigned"
    )

    return {
        "status": "success",
        "action": "status_updated_to_unassigned",
        "order_number": food_order.order_number,
    }


async def _handle_restaurant_timedout(
    delivery_summary: DeliverySummaryData,
    restaurant_admins: List[str],
) -> dict:
    """
    Handle restaurant_timedout trigger: auto-accept order and notify admins.

    Args:
        delivery_summary: Delivery summary data
        restaurant_admins: List of admin phone numbers to notify

    Returns:
        dict: Status response with order_number
    """
    logger.info(
        f"rest_id={delivery_summary.rest_id}, rest_name={delivery_summary.rest_name}"
    )
    # on timedout, pickup_time should be 30 mins from delivery_summary.dtts, also update status='assigned', restaurant_confirmation_status='auto_accept'

    order_time = parse_db_iso(delivery_summary.dtts).astimezone(UK_TZ)
    new_pickuptime = (order_time + timedelta(minutes=30)).isoformat()
    pickup_display = fmt_uk_time(order_time + timedelta(minutes=30))

    update_vals = {
        "status": "unassigned",
        "restaurant_confirmation_status": "auto_accept",
        "pickup_time": new_pickuptime,
    }

    order_number = delivery_summary.order_number

    # Send auto-accept notification to all admins
    for admin_phone in restaurant_admins:
        await _async_wa_client.send_message(
            to=admin_phone,
            text=f"Order {order_number} auto-accepted due to confirmation timeout. Pickup time set to {pickup_display} (30 mins from order time).",
        )

    # pylint: disable=unused-variable
    result = await asyncio.to_thread(
        lambda: (
            client_ordelo.table("delivery_summary")
            .update(update_vals)
            .eq("order_number", order_number)
            .execute()
        )
    )

    return {
        "status": "success",
        "action": "restaurant_timedout_logged",
    }


@router.post("/restaurant-confirmation-request")
async def restaurant_confirmation_flow(
    background_tasks: BackgroundTasks,
    payload: dict = Depends(get_payload),
):
    """
    Webhook triggered for restaurant confirmation workflow events.
    Handles: restaurant_unconfirmed (new order), restaurant_accept, restaurant_decline, restaurant_timedout.

    Triggered by:
    - Database trigger on delivery_summary INSERT with restaurant_confirmation_status='restaurant_unconfirmed'
    - Database trigger on delivery_summary UPDATE to restaurant_confirmation_status='restaurant_accept', 'restaurant_decline', or 'restaurant_timedout'

    Payload structure:
    {
        "trigger_reason": "restaurant_unconfirmed" | "restaurant_accept" | "restaurant_decline" | "restaurant_timedout",
        "delivery_summary": DeliverySummaryData model data,
        "restaurant_master": RestaurantMasterData model data,
        "food_order": FoodOrder model data,
        "order_items": List[OrderItem] model data
    }

    Returns:
        dict: Status of the operation and order_number (handlers run in background)
    """
    try:
        # Parse payload into Pydantic models
        confirmation_payload = RestaurantConfirmationPayload(**payload)
        trigger_reason = confirmation_payload.trigger_reason
        delivery_summary = confirmation_payload.delivery_summary
        restaurant_master = confirmation_payload.restaurant_master
        food_order = confirmation_payload.food_order
        order_items = confirmation_payload.order_items

        logger.info(
            f"Restaurant confirmation webhook triggered: trigger_reason={trigger_reason}, "
            f"order={food_order.order_number}, rest_id={delivery_summary.rest_id}, "
            f"rest_name={delivery_summary.rest_name}, total_price={food_order.total_price}"
        )

        # Validate admin contacts exist
        if not restaurant_master.admins or len(restaurant_master.admins) == 0:
            logger.error(
                f"No admin contacts found for restaurant {delivery_summary.rest_id}"
            )
            return {
                "status": "error",
                "message": "No restaurant contacts",
                "order_number": food_order.order_number,
            }

        # Route to appropriate handler based on trigger_reason (run as background task)
        if trigger_reason == "restaurant_unconfirmed":
            background_tasks.add_task(
                _handle_restaurant_unconfirmed,
                delivery_summary,
                restaurant_master,
                food_order,
                order_items,
            )
        elif trigger_reason == "restaurant_accept":
            background_tasks.add_task(
                _handle_restaurant_accept,
                delivery_summary,
                restaurant_master,
                food_order,
                order_items,
            )
        elif trigger_reason == "restaurant_decline":
            background_tasks.add_task(
                _handle_restaurant_decline, delivery_summary, food_order
            )
        elif trigger_reason == "restaurant_timedout":
            background_tasks.add_task(
                _handle_restaurant_timedout, delivery_summary, restaurant_master.admins
            )
        else:
            logger.error(f"Unknown trigger_reason: {trigger_reason}")
            return {
                "status": "error",
                "message": f"Unknown trigger_reason: {trigger_reason}",
                "order_number": food_order.order_number,
            }

        return {
            "status": "accepted",
            "message": f"Handler for {trigger_reason} scheduled",
            "order_number": food_order.order_number,
        }

    except Exception as e:
        logger.error(f"Error in restaurant_confirmation_request_hook: {e}")
        return {
            "status": "error",
            "message": str(e),
            "order_number": payload.get("food_order", {}).get(
                "order_number", "unknown"
            ),
        }
