"""
R3: web-origin isolation and customer tracking safeguards.

Takeaway webhook handlers for restaurant confirmation and pickup time events.
    . Processes takeaway restaurant confirmation workflow events via DB trigger webhooks
    . Handles restaurant_unconfirmed, restaurant_accept, restaurant_decline, restaurant_timedout
    . Returns pickup_time trigger webhooks quickly and runs print/notification work in background
    . Guards timeout auto-accept updates so stale timeout work cannot overwrite selected pickup times
    . Preserves pickup-finalized operations and sends restaurant-admin receipts
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
    . Routes customer notifications through the R1b notifier (always on since R3.1)
"""

from utils_common.order_management.customer_keys import is_web_customer_key
from utils_common.notify import customer_notifier
from utils_common.notify.customer_notifier import CustomerOrderEvent
# %%
import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from utils_common.tz_utils import UK_TZ, fmt_uk_time, parse_db_iso, to_uk_epoch
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, ValidationError
import httpx

from config import (
    _async_wa_client,
    client_ordelo,
    logger,
    ms_settings
)
from utils_common.order_management.food_order_pymodel import FoodOrder
from utils_common.order_management.order_db_ops_new import OrderItem
from utils_common.notify import restaurant_notifier
from utils_common.notify.restaurant_notifier import AutoAccepted, TakeawayReceipt
from utils_common.waba_utils.wa_senders import (
    send_restaurant_order_confirmation,
    send_restaurant_pickup_time,
)
from watomation.routers.delivery_hooks import cancel_payment, notify_overwatch
from utils_common.payment_ms.payment import (
    generate_automatic_payment_url,
)


_CAPTURE_LOOKUP_RETRY_DELAYS_SECONDS = (2, 5)
_PAYMENT_INTENT_LOOKUP_FAILURE = "failed to retrieve paymentintent from order number"


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

    cancel_result = None
    if food_order.payment_status != "pay_at_rest":
        try:
            cancel_result = await cancel_payment(order_number=food_order.order_number)
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

    if is_web_customer_key(takeaway_summary.customer_id):
        if cancel_result is None and food_order.payment_status != "pay_at_rest":
            from utils_common.web_ordering.lifecycle import queue_release
            await queue_release(food_order.order_number, "restaurant_declined")
        await customer_notifier.publish(food_order.order_number, CustomerOrderEvent(
            "restaurant_declined", "restaurant_declined", "web-restaurant-declined", {"payment_cancelled": cancel_result is not None}))
    else:
        await _async_wa_client.send_message(to=takeaway_summary.customer_id, text=customer_text)

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

    await restaurant_notifier.notify(
        AutoAccepted(takeaway_summary.order_number, "takeaway", restaurant_admins, pickup_display, pickup_minutes, rest_ref)
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
    payload = {
        "takeaway_summary": takeaway_summary.model_dump(),
        "restaurant_master": restaurant_master.model_dump(),
    }
    await customer_notifier.publish(takeaway_summary.order_number, CustomerOrderEvent(
        "pickup_time_set", f"pickup_time_set:{takeaway_summary.pickup_time}",
        "order-pickup-time-updated", payload, follow_redirects=True, is_estimate=True))


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
        await _notify_capture_reconciliation(order_number, "food order was not found")
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
        await _notify_capture_reconciliation(
            order_number,
            f"payment status was {payment_status!r}, not requires_capture",
        )
        return None

    # Configured auto-accept can set pickup_time immediately after Stripe
    # authorization. The payment-service webhook may still be persisting the
    # PaymentIntent, so only its explicit pre-capture lookup error is retried.
    # Every other failure may be ambiguous and needs reconciliation instead.
    async with httpx.AsyncClient() as _client:
        for attempt, retry_delay in enumerate(
            (*_CAPTURE_LOOKUP_RETRY_DELAYS_SECONDS, None), start=1
        ):
            res = None
            logger.info(
                f"Capturing takeaway payment for order {order_id} (attempt {attempt}) "
                f"with payment URI: {payment_uri}"
            )
            try:
                capture_payload = await food_order.gen_capture_payload()
                capture_payload["restaurant_confirmation_code"] = "N/A"
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
            except httpx.HTTPStatusError as error:
                response_text = res.text if res is not None else ""
                is_safe_lookup_retry = (
                    res is not None
                    and res.status_code == 500
                    and _PAYMENT_INTENT_LOOKUP_FAILURE in response_text.lower()
                    and retry_delay is not None
                )
                if is_safe_lookup_retry:
                    logger.warning(
                        f"PaymentIntent is not stored yet for order {order_id}; "
                        f"retrying capture in {retry_delay} seconds"
                    )
                    await asyncio.sleep(retry_delay)
                    continue

                logger.error(
                    f"Payment capture failed for order {order_id}: {error}; "
                    f"response={response_text}"
                )
                await _notify_capture_reconciliation(
                    order_number,
                    response_text or str(error),
                )
                return None
            except httpx.HTTPError as error:
                logger.error(
                    f"Payment capture transport failure for order {order_id}: {error}"
                )
                await _notify_capture_reconciliation(order_number, str(error))
                return None


async def _notify_capture_reconciliation(order_number: str, reason: str) -> None:
    """Alerts Overwatch without aborting later pickup-time background tasks."""
    try:
        await notify_overwatch(
            log_msg=(
                f"{order_number} takeaway payment capture requires reconciliation: {reason}"
            )
        )
    except Exception:
        logger.exception(
            f"Failed to send capture reconciliation alert for takeaway order {order_number}"
        )

# %%

@router.post("/pickup-time-updated")
async def pickup_time_updated_hook(
    background_tasks: BackgroundTasks,
    payload: dict = Depends(get_payload),
):
    """Webhook triggered when takeaway_summary.pickup_time is set (NULL → non-NULL).

    Triggered by: trigger_takeaway_pickup_time_set on takeaway_summary
    Source Function: takeaway_pickup_time_whook() in ordelo_datamodels/takeaway/takeaway_summary.sql
    """
    if "takeaway_summary" not in payload or payload["takeaway_summary"] is None:
        logger.error("No takeaway_summary found: from pickup_time_updated_hook")
        return {"status": "error", "data": payload}

    try:
        takeaway_summary = TakeawaySummaryData(**payload["takeaway_summary"])
        restaurant_master = RestaurantMasterData(**payload["restaurant_master"])
    except (KeyError, TypeError, ValidationError) as error:
        summary_payload = payload.get("takeaway_summary")
        order_number = (
            summary_payload.get("order_number", "unknown")
            if isinstance(summary_payload, dict)
            else "unknown"
        )
        logger.error(f"Invalid pickup-time webhook payload for order {order_number}: {error}")
        return {
            "status": "error",
            "message": "Invalid pickup-time webhook payload",
            "order_number": order_number,
        }

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

    # 3. Send the operational receipt for every pickup-confirmed takeaway,
    # including configured auto-accept orders.
    logger.info("step3: send admin order receipt")
    background_tasks.add_task(
        restaurant_notifier.notify,
        TakeawayReceipt(
            order_number=takeaway_summary.order_number,
            pickup_time=takeaway_summary.pickup_time,
            rest_name=takeaway_summary.rest_name or restaurant_master.rest_name,
            admins=restaurant_master.admins,
            restaurant_msg_id=takeaway_summary.restaurant_msg_id,
            rest_ref=takeaway_summary.rest_ref or restaurant_master.rest_ref,
        ),
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
