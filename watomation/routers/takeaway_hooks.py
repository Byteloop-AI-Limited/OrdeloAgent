"""
Takeaway webhook handlers for restaurant confirmation and pickup time events.
    . Processes takeaway restaurant confirmation workflow events via DB trigger webhooks
    . Handles restaurant_unconfirmed, restaurant_accept, restaurant_decline, restaurant_timedout
    . Returns pickup_time trigger webhooks quickly and runs print/notification work in background
    . Guards timeout auto-accept updates so stale timeout work cannot overwrite selected pickup times
    . Initializes takeaway_summary via RPC for pay-at-restaurant orders
    . Uses BackgroundTasks to avoid DB trigger HTTP timeouts
  Functions/Classes:
    . TakeawaySummaryData - Pydantic model for takeaway_summary table fields
    . RestaurantMasterData - Pydantic model for restaurant_master table fields
    . TakeawayConfirmationPayload - Payload model for restaurant confirmation webhook
    . _format_pickup_time_display - Formats pickup time for human-readable display
    . init_takeaway_summary - Background task to initialize takeaway_summary via RPC
    . _handle_restaurant_unconfirmed - Sends order confirmation request to restaurant admins
    . _handle_restaurant_accept - Sends pickup time selection to restaurant admins
    . _handle_restaurant_decline - Handles restaurant decline with payment cancellation
    . _handle_restaurant_timedout - Auto-accepts order and sets default pickup time
    . restaurant_confirmation_flow - Webhook endpoint for restaurant confirmation events
    . _post_pickup_time_event - POSTs pickup-time-updated event to restaurant webhook service
    . pickup_time_updated_hook - Webhook endpoint for pickup_time set events
    . init_takeaway_order - Direct entrypoint for pay-at-restaurant takeaway orders
"""
# %%
import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from utils_common.tz_utils import UK_TZ, fmt_uk_time, parse_db_iso, to_uk_epoch
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel
import httpx

from config import (
    _async_wa_client,
    client_ordelo,
    get_restaurant_webhook_url_async,
    logger,
    ms_settings
)
from utils_common.order_management.food_order_pymodel import FoodOrder
from utils_common.order_management.order_db_ops_new import OrderItem
from utils_common.waba_utils.wa_senders import (
    send_restaurant_order_confirmation,
    send_restaurant_pickup_time,
    takeaway_admin_order_receipt,
)
from watomation.routers.delivery_hooks import cancel_payment, notify_overwatch
from utils_common.payment_ms.payment import (
    generate_automatic_payment_url,
    generate_payment_intent_url,
)


async def get_payload(request: Request):
    return await request.json()


router = APIRouter(tags=["takeaway_hooks"])


class TakeawaySummaryData(BaseModel):
    """takeaway_summary fields from takeaway trigger payload."""

    order_number: str
    rest_id: str
    rest_name: str
    rest_address: str
    town: str
    customer_id: str
    customer_name: str
    restaurant_confirmation_status: str
    restaurant_update_dtts: Optional[str] = None
    restaurant_admin: Optional[str] = None
    status: str
    rest_confirmation_code: int
    rest_prep_time_minutes: Optional[int] = None
    rest_confirmation_method: Optional[str] = None
    restaurant_msg_id: Optional[str] = None
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


class TakeawayConfirmationPayload(BaseModel):
    """Payload model for takeaway confirmation webhook."""

    trigger_reason: str
    takeaway_summary: TakeawaySummaryData
    restaurant_master: RestaurantMasterData
    food_order: FoodOrder
    order_items: List[OrderItem]


def _format_pickup_time_display(pickup_time_iso: str) -> str:
    return fmt_uk_time(pickup_time_iso)


def init_takeaway_summary(order_number: str, recipient: str):
    """Background task to initialize takeaway_summary via RPC call."""
    from config.params import _resolve_rest_ref

    try:
        rest_ref = order_number.split("-")[0]
        rest_ref = _resolve_rest_ref(rest_ref)
        # Resolve the rest_ref so that rest_master table is picked with right restaurant
        response = client_ordelo.rpc(
            "init_takeaway",
            {
                "p_cust_id": recipient,
                "p_order_number": order_number,
                "p_rest_ref": rest_ref,
            },
        ).execute()
        logger.info(
            f"init_takeaway completed for order {order_number} with response {response}"
        )
    except Exception as e:
        logger.error(f"init_takeaway failed for order {order_number}: {e}")


async def _handle_restaurant_unconfirmed(
    takeaway_summary: TakeawaySummaryData,
    restaurant_master: RestaurantMasterData,
    food_order: FoodOrder,
    order_items: List[OrderItem],
) -> dict:
    order_items_str = ", ".join(
        [f"{item.quantity}x {item.product_name}" for item in order_items]
    )
    order_amount = f"£{food_order.total_price:.2f}"

    order_time_epoch = to_uk_epoch(takeaway_summary.dtts)

    for admin_phone in restaurant_master.admins:
        await send_restaurant_order_confirmation(
            recipient=admin_phone,
            order_number=food_order.order_number,
            order_amount=order_amount,
            order_items=order_items_str,
            order_time=order_time_epoch,
            order_type="takeaway",
        )

    return {
        "status": "success",
        "action": "confirmation_sent",
        "order_number": food_order.order_number,
    }


async def _handle_restaurant_accept(
    takeaway_summary: TakeawaySummaryData,
    restaurant_master: RestaurantMasterData,
    food_order: FoodOrder,
    order_items: List[OrderItem],
) -> dict:
    order_items_str = ", ".join(
        [f"{item.quantity}x {item.product_name}" for item in order_items]
    )
    order_time_epoch = to_uk_epoch(takeaway_summary.dtts)

    header = f"Order {food_order.order_number} - Pickup Time"
    text = f"Order accepted! Items: {order_items_str}\n\nPlease select estimated pickup time:"

    for admin in restaurant_master.admins:
        await send_restaurant_pickup_time(
            recipient=admin,
            header=header,
            text=text,
            order_number=food_order.order_number,
            order_time_epoch=order_time_epoch,
            intervals_mins=[5, 15, 25],
            order_type="takeaway",
        )

    return {
        "status": "success",
        "action": "pickup_time_sent",
        "order_number": food_order.order_number,
    }


async def _handle_restaurant_decline(
    takeaway_summary: TakeawaySummaryData,
    food_order: FoodOrder,
) -> dict:
    await asyncio.to_thread(
        lambda: (
            client_ordelo.table("takeaway_summary")
            .update(
                {
                    "status": "declined",
                    "restaurant_update_dtts": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("order_number", food_order.order_number)
            .execute()
        )
    )

    if food_order.payment_status != "pay_at_rest":
        try:
            await cancel_payment(order_number=food_order.order_number)
        except Exception:
            logger.exception(
                "Payment cancellation failed during takeaway decline",
                extra={"order_number": food_order.order_number},
            )
        customer_text = (
            f"Sorry, your order {food_order.order_number} could not be accepted by {takeaway_summary.rest_name}.\n"
            "Your payment has been cancelled."
        )
    else:
        customer_text = f"Sorry, your order {food_order.order_number} could not be accepted by {takeaway_summary.rest_name}."

    await _async_wa_client.send_message(
        to=takeaway_summary.customer_id, text=customer_text
    )

    return {
        "status": "success",
        "action": "declined",
        "order_number": food_order.order_number,
    }


def _get_pickup_default_minutes(rest_ref: str) -> int:
    for key in [f"{rest_ref.upper()}_DEFAULT_COLLECTION_PICKUP_TIME", "DEFAULT_COLLECTION_PICKUP_TIME"]:
        resp = (
            client_ordelo.table("ordelo_config")
            .select("config_value")
            .eq("config_key", key)
            .limit(1)
            .execute()
        )
        logger.info(f"Config response for {key}: {resp.data}")
        if resp.data:
            return int(float(resp.data[0]["config_value"]))
    return 30


async def _handle_restaurant_timedout(
    takeaway_summary: TakeawaySummaryData,
    restaurant_admins: List[str],
) -> dict:
    rest_ref = takeaway_summary.rest_ref or takeaway_summary.order_number.split("-")[0]
    pickup_minutes = await asyncio.to_thread(_get_pickup_default_minutes, rest_ref)
    logger.info(f"Pickup minutes for {rest_ref}: {pickup_minutes}")

    order_time = parse_db_iso(takeaway_summary.dtts).astimezone(UK_TZ)
    new_pickup_time = (order_time + timedelta(minutes=pickup_minutes)).isoformat()
    pickup_display = fmt_uk_time(order_time + timedelta(minutes=pickup_minutes))

    result = await asyncio.to_thread(
        lambda: (
            client_ordelo.table("takeaway_summary")
            .update(
                {
                    "status": "pickup_confirmed",
                    "restaurant_confirmation_status": "auto_accept",
                    "pickup_time": new_pickup_time,
                    "restaurant_update_dtts": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("order_number", takeaway_summary.order_number)
            .eq("restaurant_confirmation_status", "restaurant_timedout")
            .filter("pickup_time", "is", "null")
            .execute()
        )
    )

    if not result.data:
        logger.info(
            "Skipped timeout auto-accept for takeaway order %s; order state changed or pickup_time already set",
            takeaway_summary.order_number,
        )
        return {
            "status": "skipped",
            "action": "auto_accept_skipped",
            "order_number": takeaway_summary.order_number,
        }

    for admin_phone in restaurant_admins:
        await _async_wa_client.send_message(
            to=admin_phone,
            text=(
                f"Order {takeaway_summary.order_number} auto-accepted due to confirmation timeout. "
                f"Pickup time set to {pickup_display} ({pickup_minutes} mins from order time)."
            ),
        )

    return {
        "status": "success",
        "action": "auto_accept",
        "order_number": takeaway_summary.order_number,
    }


@router.post("/restaurant-confirmation-request")
async def restaurant_confirmation_flow(
    background_tasks: BackgroundTasks,
    payload: dict = Depends(get_payload),
):
    """Webhook triggered for takeaway restaurant confirmation workflow events."""
    try:
        confirmation_payload = TakeawayConfirmationPayload(**payload)
        trigger_reason = confirmation_payload.trigger_reason
        takeaway_summary = confirmation_payload.takeaway_summary
        restaurant_master = confirmation_payload.restaurant_master
        food_order = confirmation_payload.food_order
        order_items = confirmation_payload.order_items

        logger.info(
            f"Takeaway confirmation webhook triggered: trigger_reason={trigger_reason}, "
            f"order={food_order.order_number}, rest_id={takeaway_summary.rest_id}, "
            f"rest_name={takeaway_summary.rest_name}, total_price={food_order.total_price}"
        )

        if trigger_reason in {"restaurant_unconfirmed", "restaurant_accept"}:
            if not restaurant_master.admins:
                return {
                    "status": "error",
                    "message": "No restaurant contacts",
                    "order_number": food_order.order_number,
                }

        if trigger_reason == "restaurant_unconfirmed":
            background_tasks.add_task(
                _handle_restaurant_unconfirmed,
                takeaway_summary,
                restaurant_master,
                food_order,
                order_items,
            )
        elif trigger_reason == "restaurant_accept":
            background_tasks.add_task(
                _handle_restaurant_accept,
                takeaway_summary,
                restaurant_master,
                food_order,
                order_items,
            )
        elif trigger_reason == "restaurant_decline":
            background_tasks.add_task(
                _handle_restaurant_decline,
                takeaway_summary,
                food_order,
            )
        elif trigger_reason == "restaurant_timedout":
            background_tasks.add_task(
                _handle_restaurant_timedout,
                takeaway_summary,
                restaurant_master.admins,
            )
        else:
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
        logger.error(f"Error in takeaway restaurant confirmation hook: {e}")
        return {
            "status": "error",
            "message": str(e),
            "order_number": payload.get("food_order", {}).get(
                "order_number", "unknown"
            ),
        }


async def _post_pickup_time_event(
    takeaway_summary: TakeawaySummaryData,
    restaurant_master: RestaurantMasterData,
) -> None:
    rest_ref = takeaway_summary.rest_ref or takeaway_summary.order_number.split("-")[0]
    webhook_url = await get_restaurant_webhook_url_async(rest_ref, "order-pickup-time-updated")
    payload = {
        "takeaway_summary": takeaway_summary.model_dump(),
        "restaurant_master": restaurant_master.model_dump(),
    }
    async with httpx.AsyncClient(follow_redirects=True) as http_client:
        res = await http_client.post(webhook_url, json=payload)
        res.raise_for_status()
    logger.info(
        f"Pickup time event posted for order {takeaway_summary.order_number} to {webhook_url}"
    )


# %%

async def capture_takeaway_payment(order_number: str):
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

    # If payment status is pay_at_rest, generate a print request
    payment_status = food_order.payment_status
    if payment_status == "pay_at_rest":
        payment_url = await generate_automatic_payment_url(
            food_order,
            is_print_only=True,
        )
        logger.info(f"Only issue a print request {payment_url}")
        return None
    
    # Validate payment status
    if payment_status != "requires_capture":
        logger.error(f"Invalid payment status for order {order_id}: {payment_status}")
        return None
    
    # if payment_status == 'requires_capture', capture the payment
    async with httpx.AsyncClient() as _client:
        logger.info(
            f"Capturing payment for order {order_id} with payment URI: {payment_uri}"
        )
        try:
            capture_payload = await food_order.gen_capture_payload()
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

@router.post("/pickup-time-updated")
async def pickup_time_updated_hook(
    background_tasks: BackgroundTasks,
    payload: dict = Depends(get_payload),
):
    """Webhook triggered when takeaway_summary.pickup_time is set (NULL → non-NULL).

    Triggered by: trigger_takeaway_pickup_time_set on takeaway_summary
    Source Function: takeaway_pickup_time_whook() in ordelo_datamodels/takeaway_summary.sql
    """
    if "takeaway_summary" not in payload or payload["takeaway_summary"] is None:
        logger.error("No takeaway_summary found: from pickup_time_updated_hook")
        return {"status": "error", "data": payload}

    takeaway_summary = TakeawaySummaryData(**payload["takeaway_summary"])
    restaurant_master = RestaurantMasterData(**payload["restaurant_master"])

    logger.info(
        f"Takeaway pickup time webhook triggered: order={takeaway_summary.order_number}, "
        f"pickup_time={takeaway_summary.pickup_time}, rest_id={takeaway_summary.rest_id}"
    )

    # 1. Capture Stripe payment
    logger.info("step1: capture takeaway payment")
    background_tasks.add_task(capture_takeaway_payment, takeaway_summary.order_number)

    # 2. Call restaurant webhook - pickup-time-updated event
    logger.info("step2: call restaurant webhook - pickup-time-updated")
    background_tasks.add_task(_post_pickup_time_event, takeaway_summary, restaurant_master)

    # 3. Send admin order receipt
    logger.info("step3: send admin order receipt")
    background_tasks.add_task(
        takeaway_admin_order_receipt,
        order_number=takeaway_summary.order_number,
        pickup_time=takeaway_summary.pickup_time,
        rest_name=takeaway_summary.rest_name or restaurant_master.rest_name,
        admins=restaurant_master.admins,
        restaurant_msg_id=takeaway_summary.restaurant_msg_id,
        rest_ref=takeaway_summary.rest_ref or restaurant_master.rest_ref,
    )

    # 4. Notify overwatch
    logger.info("step4: notify overwatch")
    background_tasks.add_task(
        notify_overwatch,
        log_msg=f"{takeaway_summary.order_number} takeaway pickup time set",
    )

    return {"status": "success"}


# Where is this called?
@router.post("/init-takeaway-order")
async def init_takeaway_order(
    background_tasks: BackgroundTasks,
    payload: dict = Depends(get_payload),
):
    """Direct entrypoint for pay-at-restaurant takeaway orders."""
    order_number = payload["order_number"]
    customer_id = payload.get("customer_id") or payload.get("recipient")
    if not customer_id:
        return {"status": "error", "message": "customer_id is required"}

    background_tasks.add_task(init_takeaway_summary, order_number, customer_id)
    return {"status": "accepted", "order_number": order_number}
