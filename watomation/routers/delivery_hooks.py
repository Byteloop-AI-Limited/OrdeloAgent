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
    . Manages thread lifecycle including automatic closure for inactive threads
    . Implements restaurant confirmation touchpoint before rider dispatch
    . Uses module-level WhatsApp client for confirmation workflow
    . Uses DeliverySummaryData, RestaurantMasterData, FoodOrder and OrderItem Pydantic models for restaurant confirmation payload
  Functions/Classes:
    . DeliverySummaryData - Pydantic model for delivery_summary table fields
    . RestaurantMasterData - Pydantic model for restaurant_master table fields
    . RestaurantConfirmationPayload - Pydantic model for restaurant confirmation webhook with trigger_reason
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
    . shift_availability_enquiry_hook - Processes shift availability enquiries
    . restaurant_confirmation_request_hook - Accepts FoodOrder and List[OrderItem] for restaurant confirmation
    . close_threads - Closes inactive threads and sends goodbye messages
"""

# %%
from fastapi import APIRouter, Request, Depends, BackgroundTasks
from ordelo_datamodels.delivery_pymodels import DeliveryDetail
from config import logger, _async_wa_client, pg_settings
from pywa.types import Button
from pywa_async import WhatsApp
from datetime import datetime, timedelta
import json
import pytz
from psycopg_pool import AsyncConnectionPool
import asyncio
from config import client_ordelo, get_webhook_url
import httpx
from ordelo.agents.agent_runner import init_ordelo_graph
from ordelo.agents.agent_runner import run_rider_graph
from ordelo.agent_app_handlers import enquire_shift_availability
from utils_common.waba_utils.wa_templates.restaurant_confirmation_template import (
    send_restaurant_order_confirmation,
)
from utils_common.order_management.food_order_pymodel import FoodOrder
from utils_common.order_management.order_db_ops_new import OrderItem
from pydantic import BaseModel
from typing import List, Optional


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
    status: str
    rest_confirmation_code: int
    cust_confirmation_code: int
    rest_confirmed_at: Optional[str] = None
    rest_prep_time_minutes: Optional[int] = None
    rest_confirmation_method: Optional[str] = None
    pickup_time: str
    pickup_date: str
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

    pickup_time = (
        datetime.now().astimezone(pytz.timezone("Europe/London"))
        + timedelta(minutes=25)
    ).strftime("%I:%M %p")

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
        footer="♾️ Byteloop AI",
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
):
    """
    Handle shift availability enquiry webhook from PostgreSQL function.

    This endpoint processes the payload containing active riders and logs
    their information for monitoring and potential further processing.

    Args:
        payload (dict): The JSON payload containing event_type, timestamp, and riders array

    Returns:
        dict: Status of the operation and summary of processed riders
    """
    logger.info(f"shift_availability_enquiry_hook received: {payload}")

    # Extract riders from payload
    riders = payload.get("riders", [])
    event_type = payload.get("event_type", "unknown")

    # Log each rider's information
    if riders:
        logger.info(f"Processing {len(riders)} active riders for {event_type}")
        for rider in riders:
            await enquire_shift_availability(
                wa=_async_wa_client,
                recipient=rider.get("rider_id"),
                name=rider.get("rider_name"),
            )
    else:
        logger.info("No active riders found in the enquiry")

    return {"status": "success", "riders_processed": len(riders), "data": payload}


# send_restaurant_order_confirmation - Should be imported from utils_common.waba_utils.templates.restaurant_confirmation_template
@router.post("/restaurant-confirmation-request")
async def restaurant_confirmation_request_hook(
    payload: dict = Depends(get_payload),
):
    """
    Webhook triggered for restaurant confirmation workflow events.
    Handles: restaurant_unconfirmed (new order), restaurant_accept, restaurant_decline.

    Triggered by:
    - Database trigger on delivery_summary INSERT with status='restaurant_unconfirmed'
    - Database trigger on delivery_summary UPDATE to status='restaurant_accept' or 'restaurant_decline'

    Payload structure:
    {
        "trigger_reason": "restaurant_unconfirmed" | "restaurant_accept" | "restaurant_decline",
        "delivery_summary": DeliverySummaryData model data,
        "restaurant_master": RestaurantMasterData model data,
        "food_order": FoodOrder model data,
        "order_items": List[OrderItem] model data
    }

    Returns:
        dict: Status of the operation and order_number
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

        # Build order items summary string
        order_items_str = ", ".join(
            [f"{item.quantity}x {item.product_name}" for item in order_items]
        )

        # Calculate total order amount
        order_amount = f"£{food_order.total_price:.2f}"

        # Get order time from delivery_summary.dtts and convert to epoch time
        order_time_dt = datetime.fromisoformat(delivery_summary.dtts)
        order_time_epoch = int(order_time_dt.timestamp())

        # Get admin contacts from restaurant_master (already in payload)
        if not restaurant_master.admins or len(restaurant_master.admins) == 0:
            logger.error(
                f"No admin contacts found for restaurant {delivery_summary.rest_id}"
            )
            return {
                "status": "error",
                "message": "No restaurant contacts",
                "order_number": food_order.order_number,
            }

        # Get first admin contact
        admin_phone = restaurant_master.admins[0]

        # wa_response = send_restaurant_order_confirmation(
        #     recipient=admin_phone,
        #     order_number=food_order.order_number,
        #     order_amount=order_amount,
        #     order_items=order_items_str,
        #     order_time=order_time_epoch,
        # )
        # logger.info(f"WhatsApp response: {wa_response}")

        logger.info(
            f"Restaurant confirmation request sent for order {food_order.order_number} to {admin_phone}"
        )
        return {
            "status": "success",
            "order_number": food_order.order_number,
            "sent_to": admin_phone,
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
