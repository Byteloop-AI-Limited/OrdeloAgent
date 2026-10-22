"""
R3: web-origin isolation and customer tracking safeguards.

Delivery webhook handlers for Ordelo delivery system
    . Processes delivery-related webhook events from database triggers
    . Manages delivery dispatch assignments and inflight tracking
    . Cancels payments for timed out deliveries via the payment microservice
    . Implements function chaining pattern for complex workflows
    . Handles missed dispatch notifications and rider communications
    . Restricts TEST3100 dispatch and missed-notice audiences to current overwatch riders
    . Suppresses no-rider admin messages for configured auto-accept orders
    . Provides FastAPI endpoints for delivery operations
    . Uses PostgreSQL CTEs for conditional database operations
    . Follows webhook pattern where database triggers call FastAPI endpoints
    . Handles empty payloads gracefully in endpoints
    . Manages thread lifecycle including automatic closure for inactive threads
    . Implements restaurant confirmation touchpoint before rider dispatch
    . Alerts at configurable checkpoints around pickup_time across two phases (before and
      after collection) and three audiences (the rider via the agent, overwatch, or the
      restaurant's admins -- the latter two by direct send on independent schedules),
      scheduled entirely by job_rider_pickup_alerts(); this router only gates on the
      alert's phase and routes by its audience
    . Suppresses pre-pickup-only rider updates (food ready, pickup time adjusted) unless the
      order is still inflight and not yet picked up, via ordelo.delivery_progress.check_delivery_progress,
      so a late admin button tap never runs the rider agent or writes to delivery_summary
    . Uses module-level WhatsApp client for confirmation workflow
    . Uses DeliverySummaryData, RestaurantMasterData, FoodOrder and OrderItem Pydantic models for restaurant confirmation payload
    . Trigger fires on restaurant_confirmation_status changes (not status)
  Functions/Classes:
    . DeliverySummaryData - Pydantic model for delivery_summary table fields (includes restaurant_confirmation_status, restaurant_msg_id, rider_msg_id, customer_msg_id)
    . RestaurantMasterData - Pydantic model for restaurant_master table fields
    . RestaurantConfirmationPayload - Pydantic model for restaurant confirmation webhook with trigger_reason
    . get_payload - Helper to parse webhook payloads
    . cancel_payment - Cancels payment for an order via payment microservice
    . wa_send_delivery_dispatch_request_to_rider - Sends the job offer on the dispatch's channel (RiderMessenger.offer_job;
      WhatsApp byte-identical) and stores its MsgRef on delivery_dispatch.channel_msg_ref (R4, D44/D49)
    . post_rider_event_inflight - Posts delivery summary to webhook (accepts DeliverySummary param)
    . post_delivery_timedout - Posts delivery timeout information
    . delivery_hook_root - Root endpoint for delivery hooks
    . delivery_dispatch_hook - Processes dispatch assignments
    . delivery_inflight_graph_init_hook - Initializes inflight tracking
    . notify_missed_dispatches_hook - Handles missed dispatch cases (Telegram offers edited in place, WhatsApp text unchanged)
    . notify_food_ready_for_pickup - Notifies rider about food readiness (skipped after pickup)
    . delivery_timedout - Handles delivery timeout events
    . check_rider_allocation_status - Checks rider allocation status
    . shift_availability_enquiry_hook - Processes shift availability enquiries
    . admin_availability_enquiry_hook - Processes admin availability enquiries (dedupes admins shared across restaurants)
    . _process_admin_availability - Sends the enquiry once per unique admin number
    . rider_pickup_alerts_hook - Receives due pickup checkpoints from job_rider_pickup_alerts()
    . _process_rider_pickup_alerts - Delivers each due alert, gated on its phase and routed by its audience
    . restaurant_confirmation_flow - Handles restaurant confirmation workflow (unconfirmed, accept, decline, timedout)
    . _handle_restaurant_unconfirmed - Sends order confirmation request to restaurant
    . _handle_restaurant_accept - Sends pickup time selection to restaurant
    . _handle_restaurant_decline - Terminal decline (status 'declined'): cancels the payment and tells the customer (mirrors takeaway)
    . _handle_restaurant_timedout - Logs restaurant confirmation timeout event
    . _handle_restaurant_pickuptime_adjusted - Notifies the inflight rider when an admin adjusts the pickup time (skipped after pickup)
    . close_threads - Closes inactive threads and sends goodbye messages (a rider dispatch thread: exactly that thread, on
      the job's channel; every other thread as before)
    . delivery_inflight_graph_init_hook / delivery_timedout also close still-open Telegram offers of the order (D49)
    . Routes customer notifications through the R1b notifier (always on since R3.1)

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . delivery_detail (table, ordelo_datamodels/delivery/delivery_detail.sql): named in code (passed to a query helper)
  . delivery_dispatch (table, ordelo_datamodels/dispatch/delivery_dispatch.sql): named in code (passed to a query helper), updates, writes (SQL)
  . delivery_inflight (table, ordelo_datamodels/dispatch/delivery_inflight.sql): named in code (passed to a query helper), writes (SQL)
  . delivery_summary (table, ordelo_datamodels/delivery/delivery_summary.sql): reads, named in code (passed to a query helper), updates
  . food_order (table, restaurant-agents): named in code (passed to a query helper)
  . job_close_thread (function, ordelo_datamodels/agent_threads/job_close_thread.sql): calls (SQL)
  . make_threads_inactive (function, restaurant-agents): calls (SQL)
  . ordelo_config (table, ordelo_datamodels/core/ordelo_config.sql): reads, named in code (passed to a query helper)
  . rider_master (table, ordelo_datamodels/core/rider_master.sql): named in code (passed to a query helper), updates
Called by database (SQL triggers / pg_cron jobs POST to these routes):
  . admin_availability_enquiry_hook(): enquire_admin_availability() in ordelo_datamodels/restaurant_admin/enquire_admin_availability.sql via pg_cron 'enquire_admin_availability' (0 11 * * *)
  . close_threads(): job_close_thread() in ordelo_datamodels/agent_threads/job_close_thread.sql via direct calls (Python or by hand)
  . delivery_dispatch_hook(): delivery_dispatch_whook_statement() in ordelo_datamodels/dispatch/delivery_dispatch.sql via trigger trigger_delivery_dispatch_whook on delivery_dispatch; fake_delivery_dispatch_whook() in ordelo_datamodels/_orphans/dispatch.sql via nothing (orphan candidate, unused)
  . delivery_inflight_graph_init_hook(): delivery_inflight_whook() in ordelo_datamodels/dispatch/delivery_inflight.sql via trigger trigger_delivery_inflight_whook on delivery_inflight
  . delivery_timedout(): delivery_summary_timedout_whook() in ordelo_datamodels/delivery/delivery_summary.sql via trigger trigger_delivery_summary_timedout on delivery_summary
  . notify_missed_dispatches_hook(): notify_missed_dispatches() in ordelo_datamodels/dispatch/notify_missed_dispatches.sql via called by delivery_inflight_whook()
  . restaurant_confirmation_flow(): restaurant_confirmation_whook() in ordelo_datamodels/_orphans/delivery.sql via nothing (orphan candidate, unused); restaurant_updates_whook() in ordelo_datamodels/delivery/delivery_summary.sql via trigger trigger_restaurant_updates on delivery_summary
  . rider_pickup_alerts_hook(): job_rider_pickup_alerts() in ordelo_datamodels/dispatch/job_rider_pickup_alerts.sql via pg_cron 'job_rider_pickup_alert' (*/5 * * * *)
  . shift_availability_enquiry_hook(): enquire_shift_availability() in ordelo_datamodels/dispatch/enquire_shift_availability.sql via pg_cron 'enquire_shift_availability' (0 11 * * *)
(end of database objects)
"""

from utils_common.order_management.customer_keys import is_web_customer_key
from utils_common.notify import customer_notifier, restaurant_notifier
from utils_common.notify.restaurant_notifier import AutoAccepted, KitchenReceipt, RiderAlert
from utils_common.notify.customer_notifier import CustomerOrderEvent

# %%
import asyncio
from datetime import timedelta
from typing import List, Optional
from utils_common.tz_utils import UK_TZ, fmt_uk_time, parse_db_iso, to_uk_epoch
import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel
from pywa_async import WhatsApp
from config.params import get_wa_logger
from ordelo_datamodels.restaurant_master_pymodel import RestaurantMaster
from config import (
    _async_wa_client,
    client_ordelo,
    logger,
    ms_settings,
    pg_settings,
)

# from ordelo.agent_app_handlers import enquire_shift_availability
from utils_common.waba_utils.wa_senders import (
    enquire_shift_availability,
    enquire_admin_availability,
)
from ordelo.agents.agent_runner import (
    init_ordelo_graph,
    run_rider_agent_w_custom_msg,
    clear_pickup_alert_cue,
)
from ordelo.delivery_progress import DeliveryProgress, check_delivery_progress
from ordelo import dispatch_actions
from ordelo.agents import rider_threads
from ordelo.rider_messaging import JobOffer, dispatch_channel, for_dispatch, for_thread
from ordelo.rider_messaging.factory import messenger_for_dispatch
from ordelo_datamodels.delivery_pymodels import DeliverySummary
from utils_common.order_management.food_order_pymodel import FoodOrder
from utils_common.order_management.test_order_dispatch import (
    order_has_test_item, read_overwatch_riders, rider_dispatch_allowed,
)
from utils_common.order_management.order_db_ops_new import OrderItem

from utils_common.waba_utils.wa_senders import (
    send_restaurant_order_confirmation,
    send_restaurant_pickup_time,
    notify_ops_rider_alert,
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


async def capture_delivery_payment(order_number, restaurant_cc: int):
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
            if is_web_customer_key(getattr(food_order, "recipient", "")):
                await customer_notifier.publish(order_number, CustomerOrderEvent("payment_captured", "payment_captured", "web-payment-captured"))
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
            if is_web_customer_key(getattr(food_order, "recipient", "")):
                await customer_notifier.publish(order_number, CustomerOrderEvent("payment_released", "payment_released", "web-payment-released", {"payment_cancelled": True}))
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

    # Fresh membership protects stale/replayed payloads and changes since enqueue.
    if not await rider_dispatch_allowed(order_number, recipient):
        return

    pickup_time = fmt_uk_time(delivery_summary["pickup_time"])

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
    # The offer goes out on the dispatch's channel (stamped from the rider at INSERT, D44). On WhatsApp this is exactly
    # the old message with its JSON Accept / Decline payloads (ordelo/rider_messaging/whatsapp.py offer_job).
    messenger = await for_dispatch(dispatch_id, rider_id=recipient, wa_client=_async_wa_client)
    ref = await messenger.offer_job(
        JobOffer(dispatch_id=dispatch_id, order_number=order_number, header=header_text, text=wa_text)
    )
    try:
        await dispatch_actions.record_offer_ref(dispatch_id, ref)
    except Exception:
        logger.exception(f"Could not store the offer ref for dispatch {dispatch_id}")


# %% notify overwatch
async def notify_overwatch(log_msg: str):
    wa_logger = await get_wa_logger()
    await wa_logger.info(log_msg)


# %% post rider event inflight
async def post_rider_event_inflight(delivery_summary: DeliverySummary, dispatch_id: int | None = None):
    """
    Posts the delivery summary for a given order_number to the rider-inflight webhook.

    Args:
        delivery_summary (DeliverySummary): The delivery summary for the order.

    Side Effects:
        Publishes a "rider_assigned" customer event through the notifier.
    """

    payload = {
        "delivery_summary": delivery_summary.model_dump(mode="json"),
        # "delivery_detail": delivery_detail.model_dump(mode="json"),
    }
    await customer_notifier.publish(delivery_summary.order_number, CustomerOrderEvent(
        "rider_assigned", f"rider_assigned:{dispatch_id or delivery_summary.redispatch_dtts or 'initial'}",
        "rider-inflight", payload))


# %% post delivery timedout
async def post_delivery_timedout(
    delivery_summary: dict, *, payment_cancelled: bool
):
    """
    Posts the delivery summary and verified payment-cancellation outcome to the
    delivery-timedout webhook.

    Args:
        delivery_summary (dict): The payload for the delivery-timedout webhook.

    Side Effects:
        Publishes a "no_rider_found" customer event through the notifier.
    """
    await customer_notifier.publish(delivery_summary["order_number"], CustomerOrderEvent(
        "no_rider_found", "no_rider_found", "delivery-timedout",
        {**delivery_summary, "payment_cancelled": payment_cancelled}))


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
        . Restricts TEST3100 orders to overwatch riders, independent of customer identity
        . Returns immediately with status success if no dispatches
    Functions/Classes
        . delivery_dispatch_hook
        . wa_send_delivery_dispatch_request_to_rider
    Key Functions:
        . delivery_dispatch_hook - schedules dispatch sends in background

    Called by database:
      . delivery_dispatch_whook_statement() in ordelo_datamodels/dispatch/delivery_dispatch.sql via trigger trigger_delivery_dispatch_whook on delivery_dispatch
      . fake_delivery_dispatch_whook() in ordelo_datamodels/_orphans/dispatch.sql via nothing (orphan candidate, unused)
    """
    dispatches = payload.get("bulk_dispatch") or []
    if not dispatches:
        return {"status": "success"}

    classifications = {}
    overwatch = None
    for d in dispatches:
        order_number = d["order_number"]
        if order_number not in classifications:
            try:
                classifications[order_number] = await order_has_test_item(order_number)
            except Exception:
                classifications[order_number] = None
                logger.error("dispatch suppressed order={} reason=classification_unavailable", order_number)
        test_order = classifications[order_number]
        if test_order is None:
            continue
        if test_order:
            if overwatch is None:
                try:
                    overwatch = await read_overwatch_riders()
                except Exception:
                    overwatch = frozenset()
                    logger.error("test dispatch suppressed reason=membership_unavailable")
            if d["rider_id"] not in overwatch:
                logger.info("dispatch suppressed order={} reason=test_order_non_overwatch_rider", order_number)
                continue
        background_tasks.add_task(
            wa_send_delivery_dispatch_request_to_rider,
            recipient=d["rider_id"],
            delivery_summary=d,
            dispatch_id=d["dispatch_id"],
        )
        logger.info("dispatch scheduled order={} test_order={}", order_number, test_order)
    return {"status": "success"}


async def _send_missed_dispatch_if_allowed(order_number: str, to: str, text: str, dispatch_id: int | None = None):
    """Keep stale missed-notice payloads inside the same TEST3100 audience.

    WhatsApp offers get `text` exactly as before. A Telegram offer is edited in place to "Taken by another rider" with its
    buttons removed, and nothing new is sent (D49).
    """
    if not await rider_dispatch_allowed(order_number, to):
        return
    if dispatch_id is not None:
        dc = await dispatch_channel(dispatch_id)
        if dc is not None and dc.channel == "telegram":
            await messenger_for_dispatch(dc).offer_closed(dc.msg_ref, order_number, "taken")
            return
    await _async_wa_client.send_message(to=to, text=text)


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

    Called by database:
      . delivery_inflight_whook() in ordelo_datamodels/dispatch/delivery_inflight.sql via trigger trigger_delivery_inflight_whook on delivery_inflight
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
    logger.info("step1: capture stripe delivery payment")
    background_tasks.add_task(
        capture_delivery_payment, delivery_summary.order_number, rest_confirmation_code
    )

    # 2. Call restaurant webhook - rider-inflight-event (background)
    logger.info("step2: call restaurant webhook - rider-inflight-event")
    background_tasks.add_task(
        post_rider_event_inflight, delivery_summary=delivery_summary, dispatch_id=dispatch_id
    )

    # 3. Admin notification
    logger.info("step3: admin notification")
    background_tasks.add_task(
        restaurant_notifier.notify,
        KitchenReceipt(delivery_summary=delivery_summary, rider_master=rider_master, dispatch_id=dispatch_id),
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

    # 4b. Telegram offers of this order that nobody answered are edited to "Taken by another rider"; the winner's to
    #     "The job is yours" (D49). Accepted-but-lost offers are handled by /notify-missed-dispatches. WhatsApp unchanged.
    background_tasks.add_task(
        dispatch_actions.close_open_offers,
        delivery_summary.order_number,
        "taken",
        statuses=("unassigned",),
        winner_dispatch_id=dispatch_id,
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

    Called by database:
      . notify_missed_dispatches() in ordelo_datamodels/dispatch/notify_missed_dispatches.sql via called by delivery_inflight_whook()
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
                _send_missed_dispatch_if_allowed,
                order_number=order_number,
                to=rider_id,
                text=_text,
                dispatch_id=dispatch_id,
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

    Skipped once the rider's order is no longer inflight, or the food is already
    collected: a late "Ready - Notify Rider" tap or delayed restaurant-agent call
    must not run the agent. Checked via check_delivery_progress(), keyed on
    rider_id only since this webhook receives no order_number.

    A progress read failure (DeliveryProgress.UNKNOWN) also returns "skipped"
    rather than raising: the only caller (the restaurant-agent runtime's
    admin_collection_ready, in the sibling restaurant-agents repo) fires this
    with a bare ``await client.post(...)`` and never inspects the response, so
    a 5xx would be silently dropped anyway -- it would only show up as a
    spurious server-error log entry for what is, by design, a correctly
    blocked action.

    Args:
        recipient (str): The WhatsApp phone number or unique identifier of the rider.
        background_tasks (BackgroundTasks): FastAPI background task manager
        payload (dict): The JSON payload sent in the POST request body.

    Returns:
        dict: Status of the notification operation.
    """
    restaurant_name = payload.get("restaurant_name", None)

    progress, _row = await check_delivery_progress(rider_id=recipient)
    if progress is not DeliveryProgress.AWAITING_PICKUP:
        logger.info(
            f"Rider {recipient} food-ready webhook while {progress}; skipping notification"
        )
        return {
            "status": "skipped",
            "action": progress.value,
            "recipient": recipient,
            "payload": payload,
        }

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

    Called by database:
      . delivery_summary_timedout_whook() in ordelo_datamodels/delivery/delivery_summary.sql via trigger trigger_delivery_summary_timedout on delivery_summary
    """
    logger.info("delivery_timedout received")
    delivery_summary_lst = payload.get("delivery_summary", None)
    delivery_summary = delivery_summary_lst[0]
    rest_id = delivery_summary["rest_id"]

    # 1. Cancel payment. A successful cancellation endpoint response is the
    # only condition that allows the restaurant runtime to confirm a refund.
    payment_cancelled = False
    try:
        payment_cancelled = (
            await cancel_payment(order_number=delivery_summary["order_number"])
        ) is not None
    except Exception:
        logger.exception(
            "Payment cancellation failed during delivery_timedout",
            extra={"order_number": delivery_summary.get("order_number")},
        )

    if not payment_cancelled and is_web_customer_key(delivery_summary.get("customer_id")):
        from utils_common.web_ordering.lifecycle import queue_release
        await queue_release(delivery_summary["order_number"], "no_rider_found")

    # 2. Configured auto-accept orders intentionally suppress the noisy
    # no-rider message. Timeout auto-accepts retain their existing message.
    if delivery_summary.get("rest_confirmation_method") != "configured_auto":
        rest_ref = delivery_summary["order_number"].split("-")[0]
        rest_admins = RestaurantMaster.get_admins_for(rest_ref)

        for admin_phone in rest_admins:
            await _async_wa_client.send_message(
                to=admin_phone,
                text="No Rider Found for order number: " + delivery_summary["order_number"],
            )
    else:
        logger.info(
            "Skipping no-rider admin notification for configured auto-accept order %s",
            delivery_summary["order_number"],
        )

    if "test" not in delivery_summary["order_number"].lower():  # skip test orders
        background_tasks.add_task(
            post_delivery_timedout,
            delivery_summary,
            payment_cancelled=payment_cancelled,
        )

    # Telegram offers still open for this order: edit to "Offer expired" (D49). WhatsApp unchanged.
    background_tasks.add_task(
        dispatch_actions.close_open_offers,
        delivery_summary["order_number"],
        "expired",
        statuses=("unassigned", "accepted"),
    )
    return {"status": "success"}


# %% Check rider allocation status - with location handled in waLoction, this can go. To Be Deleted
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


_GOODBYE_TEXT = "Ending the converstaion, thank you and good bye 👋"


@router.post(
    "/close-threads",
    summary="Close inactive threads. Called by job_close_thread() PostgreSQL function via Supabase cron",
    description="""
    Processes thread closure requests from the scheduled job_close_thread() function.
    
    Triggered by: Supabase cron job running every 5 minutes
    Source Function: job_close_thread() in ordelo_datamodels/agent_threads/job_close_thread.sql
    
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
    """
    Called by database:
      . job_close_thread() in ordelo_datamodels/agent_threads/job_close_thread.sql via direct calls (Python or by hand)
    """
    pool = await pg_settings.get_pool()
    from utils_common.thread_management import ThreadHandler

    thread_handler = ThreadHandler(pool)
    try:
        payload = await request.json()
        print(f"Received close-threads payload: {payload}")

        # Loop through the records and close each thread
        if payload and isinstance(payload, list):
            for record in payload:
                if record.get("recipient") is None or record.get("agent") == "WEB":
                    continue
                # A rider DISPATCH thread (R2): close exactly that thread and say goodbye on the job's channel (D44).
                dispatch_thread = (
                    await rider_threads.describe(record["thread_id"]) if record.get("thread_id") else None
                )
                if dispatch_thread is not None and dispatch_thread.is_dispatch_thread:
                    await rider_threads.close(dispatch_thread.thread_id)
                    logger.info(f"Rider thread closed: {record}")
                    await for_thread(dispatch_thread, wa_client=_async_wa_client).say(_GOODBYE_TEXT)
                    continue
                # Every other thread: unchanged behaviour (see docs/to-do.md about customer threads in this payload)
                await thread_handler.make_threads_inactive(
                    recipient=record["recipient"]
                )
                logger.info(f"Thread closed: {record}")
                await _async_wa_client.send_message(
                    to=record["recipient"],
                    text=_GOODBYE_TEXT,
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

    Called by database:
      . enquire_shift_availability() in ordelo_datamodels/dispatch/enquire_shift_availability.sql via pg_cron 'enquire_shift_availability' (0 11 * * *)
    """
    logger.info(f"shift_availability_enquiry_hook received: {payload}")

    riders = payload.get("riders", [])
    event_type = payload.get("event_type", "unknown")
    rider_ids = [rider.get("rider_id") for rider in riders]

    # WhatsApp riders only (D53, R5): the SQL already sends only channel = 'whatsapp'; filtering the UPDATE as well means a
    # Telegram rider is never switched off or asked, even by an older enquire_shift_availability() or a stale payload.
    update_shift_status = (
        client_ordelo.table("rider_master")
        .update({"is_in_shift": False, "shift_response_dtts": "now()"})
        .in_("rider_id", rider_ids)
        .eq("channel", "whatsapp")
        .execute()
    )
    switched_off = {row.get("rider_id") for row in (update_shift_status.data or [])}
    riders = [rider for rider in riders if rider.get("rider_id") in switched_off]

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
    2. Dedupes admins that appear under more than one restaurant so each
       number receives a single message
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
    the availability enquiry to each admin exactly once: the same admin number
    can appear under multiple rest_refs, and the enquiry message is generic, so
    duplicate numbers are collapsed here before scheduling.
    Uses background tasks to avoid DB timeout.

    Args:
        payload (dict): The JSON payload containing event_type, timestamp, and restaurant_admins dict
        background_tasks: FastAPI BackgroundTasks for async processing

    Returns:
        dict: Status of the operation and count of unique admins to be processed

    Called by database:
      . enquire_admin_availability() in ordelo_datamodels/restaurant_admin/enquire_admin_availability.sql via pg_cron 'enquire_admin_availability' (0 11 * * *)
    """
    logger.info(f"admin_availability_enquiry_hook received: {payload}")

    restaurant_admins = payload.get("restaurant_admins", {})
    event_type = payload.get("event_type", "unknown")

    admin_rest_refs: dict = {}
    for rest_ref, admins in restaurant_admins.items():
        for admin in admins:
            admin_rest_refs.setdefault(admin, []).append(rest_ref)

    if admin_rest_refs:
        logger.info(
            f"Scheduling {len(restaurant_admins)} restaurants ({len(admin_rest_refs)} unique admins) for {event_type} processing"
        )
        background_tasks.add_task(_process_admin_availability, admin_rest_refs)
    else:
        logger.info("No restaurant admins found in the enquiry")

    return {"status": "success", "admins_scheduled": len(admin_rest_refs)}


async def _process_admin_availability(admin_rest_refs: dict):
    """Background task sending the admin availability enquiry once per unique admin number.

    Args:
        admin_rest_refs (dict): admin number -> list of rest_refs that number administers
    """
    for admin, rest_refs in admin_rest_refs.items():
        logger.info(f"Processing admin availability for {admin} (restaurants: {rest_refs})")
        try:
            await enquire_admin_availability(recipient=admin)
        except Exception as e:
            logger.error(f"Error processing admin availability for {admin}: {e}")


# %%
@router.post(
    "/rider-pickup-alerts",
    summary="Alert riders at pickup-time checkpoints. Called by job_rider_pickup_alerts() PostgreSQL function",
    description="""
    Receives the pickup checkpoints that came due on this sweep, one per rider.

    All scheduling policy (which checkpoints exist, which fired, which are
    collapsed) lives in job_rider_pickup_alerts(); the job only calls this
    endpoint when there is something to send. This endpoint gates each alert on
    delivery progress and drives the rider agent to deliver it.
    """,
    response_description="Count of alerts scheduled for delivery",
)
async def rider_pickup_alerts_hook(
    payload: dict = Depends(get_payload),
    background_tasks: BackgroundTasks = None,
):
    """
    Handle the rider pickup-alert webhook from job_rider_pickup_alerts().

    Responds immediately and does the agent runs in a background task, so the
    calling SQL function is never held open on WhatsApp/LLM latency. Note the
    job marks checkpoints 'sent' on receiving this 2xx, not on the message
    actually landing -- a failure inside the background task is logged and the
    rider is picked up by the next checkpoint rather than retried here.

    Args:
        payload (dict): {"event_type", "timestamp", "alerts": [...]}
        background_tasks: FastAPI BackgroundTasks for async processing

    Returns:
        dict: Status of the operation and count of alerts scheduled

    Called by database:
      . job_rider_pickup_alerts() in ordelo_datamodels/dispatch/job_rider_pickup_alerts.sql via pg_cron 'job_rider_pickup_alert' (*/5 * * * *)
    """
    logger.info(f"rider_pickup_alerts_hook received: {payload}")

    alerts = payload.get("alerts") or []

    if alerts:
        background_tasks.add_task(_process_rider_pickup_alerts, alerts)
    else:
        logger.info("No pickup alerts in the payload")

    return {"status": "success", "alerts_scheduled": len(alerts)}


async def _process_rider_pickup_alerts(alerts: list):
    """Background task to deliver each due pickup/delivery alert through the rider agent.

    Each alert is gated on check_delivery_progress: the sweep built this payload
    seconds ago, and a "you're late!" nag landing just after the rider verified
    the restaurant code is exactly the failure to avoid. One alert failing must
    not abort the rest, so every alert is isolated.

    The alert's phase names the DeliveryProgress the delivery must still be in --
    'awaiting_pickup' for a rider who has not collected, 'picked_up' for one who
    has collected but not delivered. job_rider_pickup_alerts() emits exactly the
    DeliveryProgress values, so the gate is an identity check rather than a
    mapping, and the SQL and Python gates cannot drift apart.

    Audience decides delivery once the gate passes: 'rider' runs the rider graph,
    'ops' escalates to overwatch, 'rest_admins' notifies the restaurant's admins --
    the latter two by direct send, on independent schedules.
    """
    for alert in alerts:
        order_number = alert.get("order_number")
        rider_id = alert.get("rider_id")
        offset_minutes = alert.get("offset_minutes")
        # Absent phase/audience means a pre-migration payload (app deployed ahead
        # of the SQL): those were all rider awaiting-pickup alerts.
        phase = alert.get("phase") or DeliveryProgress.AWAITING_PICKUP
        audience = alert.get("audience") or "rider"

        try:
            try:
                required = DeliveryProgress(phase)
            except ValueError:
                logger.error(
                    f"Pickup alert for order {order_number} has unknown phase "
                    f"{phase!r}; skipping rather than guessing"
                )
                continue

            progress, row = await check_delivery_progress(order_number=order_number)

            if progress is not required:
                logger.info(
                    f"Pickup alert for order {order_number} (phase {required}, "
                    f"offset {offset_minutes}) while {progress}; skipping"
                )
                continue

            # Prefer the rider on the live inflight row over the one the sweep
            # saw. If the original rider declined pre-pickup between the POST and
            # this task running, the order has been re-dispatched and the payload
            # names someone who no longer has the job.
            rider_id = (row or {}).get("rider_id") or rider_id
            dispatch_id = (row or {}).get("dispatch_id")

            if audience == "ops":
                # Never reaches the rider, so this is a direct send rather than a
                # run of the rider graph -- there is no agent thread to keep faithful.
                await notify_ops_rider_alert(
                    phase=str(required),
                    order_number=order_number,
                    pickup_time=alert.get("pickup_time"),
                    rider_id=rider_id,
                    rider_name=alert.get("rider_name"),
                    rest_name=alert.get("rest_name"),
                    rest_ref=alert.get("rest_ref"),
                )
            elif audience == "rest_admins":
                # Same direct-send rationale as ops. Recipients come from the
                # payload (restaurant_master.admins, read by the SQL at resolve
                # time), not RestaurantMaster.get_admins_for(): that accessor is
                # sync/cached and would need asyncio.to_thread, and the payload
                # is already the fresher read of the same column.
                await restaurant_notifier.notify(
                    RiderAlert(
                        phase=str(required),
                        order_number=order_number,
                        pickup_time=alert.get("pickup_time"),
                        rider_id=rider_id,
                        rider_name=alert.get("rider_name"),
                        rest_ref=alert.get("rest_ref"),
                        rest_admins=alert.get("rest_admins"),
                    )
                )
            elif audience == "rider":
                # order_number and pickup_time come from the payload, not from
                # whatever the thread last stored: _handle_restaurant_pickuptime_adjusted
                # only refreshes state pickup_time while AWAITING_PICKUP, so after
                # collection the thread's copy can be stale while the SQL has already
                # rescheduled due_dtts off the new time.
                try:
                    await run_rider_agent_w_custom_msg(
                        recipient=rider_id,
                        dispatch_id=dispatch_id,
                        system_msg=(
                            "call tool `notify_pickup_reminder`. A pickup alert is due "
                            "for this order."
                        ),
                        state_update_dict={
                            "pickup_alert_offset": offset_minutes,
                            "pickup_alert_phase": str(required),
                            "order_number": order_number,
                            "pickup_time": alert.get("pickup_time"),
                        },
                    )
                finally:
                    # The cue is single-use. Disarm it whatever happened, so a turn
                    # hours later cannot re-fire this alert.
                    await clear_pickup_alert_cue(rider_id, dispatch_id=dispatch_id)
            else:
                logger.error(
                    f"Pickup alert for order {order_number} has unknown audience "
                    f"{audience!r}; skipping rather than guessing"
                )
                continue

            logger.info(
                f"Pickup alert sent for order {order_number} rider {rider_id} "
                f"(audience {audience}, phase {required}, offset {offset_minutes})"
            )
        except Exception as e:
            logger.error(
                f"Error processing pickup alert for order {order_number} "
                f"rider {rider_id}: {e}"
            )


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
    Handle restaurant_decline trigger (R1-a): the order is terminal, the payment is cancelled, the customer is told.

    Mirrors takeaway_hooks._handle_restaurant_decline. The decision function
    (restaurant_order_decide, restaurant_admin/restaurant_order_decision.sql) already set
    delivery_summary.status = 'declined' atomically with the decision, so the order was never dispatchable.
    The guarded update below only covers a decline written by hand (manual SQL) that left the order
    'restaurant_unconfirmed'; it never touches an order that has moved on.

    Args:
        delivery_summary: Delivery summary data
        food_order: Food order data

    Returns:
        dict: Status response with order_number
    """
    order_number = food_order.order_number
    await asyncio.to_thread(
        lambda: (
            client_ordelo.table("delivery_summary")
            .update({"status": "declined"})
            .eq("order_number", order_number)
            .eq("restaurant_confirmation_status", "restaurant_decline")
            .eq("status", "restaurant_unconfirmed")
            .execute()
        )
    )

    cancel_result = None
    if food_order.payment_status != "pay_at_rest":
        try:
            cancel_result = await cancel_payment(order_number=order_number)
        except Exception:
            logger.exception(
                "Payment cancellation failed during delivery decline",
                extra={"order_number": order_number},
            )
        customer_text = (
            f"Sorry, your order {order_number} could not be accepted by {delivery_summary.rest_name}.\n"
            "Your payment has been cancelled."
        )
    else:
        customer_text = f"Sorry, your order {order_number} could not be accepted by {delivery_summary.rest_name}."

    if is_web_customer_key(delivery_summary.customer_id):
        if cancel_result is None and food_order.payment_status != "pay_at_rest":
            from utils_common.web_ordering.lifecycle import queue_release

            await queue_release(order_number, "restaurant_declined")
        await customer_notifier.publish(
            order_number,
            CustomerOrderEvent(
                "restaurant_declined",
                "restaurant_declined",
                "web-restaurant-declined",
                {"payment_cancelled": cancel_result is not None},
            ),
        )
    else:
        await _async_wa_client.send_message(to=delivery_summary.customer_id, text=customer_text)

    logger.info(f"Restaurant declined order {order_number}: status declined, customer notified")

    return {
        "status": "success",
        "action": "declined",
        "order_number": order_number,
    }


def _get_delivery_pickup_default_minutes(rest_ref: str) -> int:
    for key in [f"{rest_ref.upper()}_DEFAULT_DELIVERY_PICKUP_TIME", "DEFAULT_DELIVERY_PICKUP_TIME"]:
        resp = (
            client_ordelo.table("ordelo_config")
            .select("config_value")
            .eq("config_key", key)
            .limit(1)
            .execute()
        )
        if resp.data:
            return int(float(resp.data[0]["config_value"]))
    return 30


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
    rest_ref = delivery_summary.rest_ref or delivery_summary.order_number.split("-")[0]
    pickup_minutes = await asyncio.to_thread(_get_delivery_pickup_default_minutes, rest_ref)

    order_time = parse_db_iso(delivery_summary.dtts).astimezone(UK_TZ)
    new_pickuptime = (order_time + timedelta(minutes=pickup_minutes)).isoformat()
    pickup_display = fmt_uk_time(order_time + timedelta(minutes=pickup_minutes))

    update_vals = {
        "status": "unassigned",
        "restaurant_confirmation_status": "auto_accept",
        "pickup_time": new_pickuptime,
    }

    order_number = delivery_summary.order_number

    # pylint: disable=unused-variable
    result = await asyncio.to_thread(
        lambda: (
            client_ordelo.table("delivery_summary")
            .update(update_vals)
            .eq("order_number", order_number)
            .execute()
        )
    )

    # Tell the admins (WhatsApp and Telegram) AFTER the update: a failed send can no longer stop the auto-accept.
    await restaurant_notifier.notify(
        AutoAccepted(order_number, "delivery", restaurant_admins, pickup_display, pickup_minutes, rest_ref)
    )

    return {
        "status": "success",
        "action": "restaurant_timedout_logged",
    }


async def _handle_restaurant_pickuptime_adjusted(
    delivery_summary: DeliverySummaryData,
) -> dict:
    """
    Handle restaurant_pickuptime_adjusted trigger: notify the inflight rider of the
    updated pickup time.

    Resolves the assigned rider and checks progress in one call via
    check_delivery_progress(order_number=...). If the order is no longer inflight,
    or the rider has already picked up the food, logs and skips silently -- a
    pickup time is meaningless after collection. This is defence-in-depth: the
    write that fires this trigger is already gated at the source in
    admin_adjust_pickup_time, but this also covers any other path that sets
    restaurant_pickuptime_adjusted (e.g. manual SQL). Otherwise drives the rider
    agent to call the notify_pickup_time_adjusted tool, refreshing the graph
    state pickup_time with the new value before the tool reads it.

    Args:
        delivery_summary: Delivery summary data (carries the new pickup_time)

    Returns:
        dict: Status response with order_number
    """
    order_number = delivery_summary.order_number

    progress, row = await check_delivery_progress(order_number=order_number)

    if progress is not DeliveryProgress.AWAITING_PICKUP:
        action = {
            DeliveryProgress.NOT_IN_PROGRESS: "no_inflight_rider",
            DeliveryProgress.PICKED_UP: "already_picked_up",
            DeliveryProgress.UNKNOWN: "progress_unknown",
        }[progress]
        logger.info(
            f"Order {order_number} pickup-time-adjusted trigger while {progress}; "
            "skipping notification"
        )
        result = {
            "status": "skipped",
            "action": action,
            "order_number": order_number,
        }
        if row:
            result["rider_id"] = row["rider_id"]
        return result

    rider_id = row["rider_id"]

    await run_rider_agent_w_custom_msg(
        recipient=rider_id,
        dispatch_id=row.get("dispatch_id"),
        system_msg=(
            "call tool `notify_pickup_time_adjusted`. The restaurant has updated the "
            "pickup time for this order."
        ),
        state_update_dict={"pickup_time": delivery_summary.pickup_time},
    )

    return {
        "status": "success",
        "action": "pickuptime_adjusted_notified",
        "order_number": order_number,
        "rider_id": rider_id,
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

    Called by database:
      . restaurant_confirmation_whook() in ordelo_datamodels/_orphans/delivery.sql via nothing (orphan candidate, unused)
      . restaurant_updates_whook() in ordelo_datamodels/delivery/delivery_summary.sql via trigger trigger_restaurant_updates on delivery_summary
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
        elif trigger_reason == "restaurant_pickuptime_adjusted":
            background_tasks.add_task(
                _handle_restaurant_pickuptime_adjusted, delivery_summary
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
