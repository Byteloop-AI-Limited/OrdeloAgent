"""
WhatsApp callback button handler for delivery dispatch responses
    . Processes rider responses to delivery dispatch assignments
    . Validates callback data and updates delivery status
    . Integrates with OrdeloAgent delivery graph logic
    . Handles cases where jobs are no longer available
    . Provides feedback to riders about dispatch status
    . Checks for existing inflight deliveries to prevent conflicts
    . Allows assigned rider to decline the same inflight job pre‑pickup, forwarding to cancel flow
    . Serves as entry point into the LangGraph agent workflow
    . Processes restaurant confirmation of food preparation time
    . Uses asyncio.create_task for long-running RPC calls to avoid timeouts
  Functions/Classes:
    . dispatch_response - Processes rider responses to delivery dispatch assignments
    . rider_request_location - Handles rider requests for location information
    . handle_shift_availability - Handles rider shift availability responses
    . handle_admin_availability - Handles admin availability responses for order notifications
    . handle_restaurant_confirmation - Processes restaurant prep time confirmation
    . restaurant_order_accept_decline_handler - Handles restaurant accept/decline responses
    . _update_restaurant_order_status - Background task for updating restaurant order status
"""

# %%
import asyncio
from pywa_async import WhatsApp, filters
from config import logger
from pywa.types import Message
import json

# project modules
from ordelo.agent_app_handlers import initial_handle_of_rider_response
from config import client_ordelo
from ordelo.agents.agent_runner import run_rider_agent_w_custom_msg
from utils_common.waba_utils.wa_senders import CallbackButtonData
from datetime import datetime, timezone
from config.params import get_restaurant_base_url_async
import httpx

# from utils_common.waba_utils.wa_senders import send_restaurant_pickup_time
from pywa.types import CallbackButton
# %%


IS_DISPATCH_RESPONSE = filters.contains("/dispatchResponse", ignore_case=False)


async def dispatch_response(wa: WhatsApp, msg: Message):
    """
    Rider's response to delivery dispatch. This is a blocking operation. Entry point into the graph.
    """
    # get app state resources
    recipient = msg.sender

    callback_data: dict = json.loads(msg.data)
    # remove command from callback data and add rider_id
    callback_data.pop("command")
    callback_data["rider_id"] = recipient
    order_number = callback_data["order_number"]

    # If order is not found
    order_status = (
        client_ordelo.table("delivery_summary")
        .select("status")
        .eq("order_number", order_number)
        .execute()
    )

    if len(order_status.data) == 0:
        logger.error(
            "No delivery detail found for order number: {}".format(order_number)
        )
        await wa.send_message(
            to=recipient, text="Sorry, This job is no longer available"
        )
        return

    # Check inflight status for this order_number first
    inflight_for_order = (
        client_ordelo.table("delivery_inflight")
        .select("*")
        .eq("order_number", order_number)
        .execute()
    )
    if len(inflight_for_order.data) > 0:
        inflight_row = inflight_for_order.data[0]
        if inflight_row["rider_id"] == recipient:
            inflight_dispatch_id = inflight_row.get("dispatch_id")
            callback_dispatch_id = callback_data.get("dispatch_id")
            is_decline_for_same_dispatch = (
                callback_data.get("status") == "declined"
                and inflight_dispatch_id is not None
                and callback_dispatch_id == inflight_dispatch_id
            )

            if not is_decline_for_same_dispatch:
                # Same rider is already on this job; ignore stale accept/decline taps
                logger.info(
                    "Rider %s already inflight for order %s",
                    recipient,
                    order_number,
                )
                await wa.send_message(
                    to=recipient,
                    text=f"Sorry, You are already on a job {inflight_row['order_number']}",
                )
                return

            # Assigned rider declining their own inflight dispatch:
            # fall through to initial_handle_of_rider_response() to trigger cancel flow.
            logger.info(
                f"Rider {recipient} declining inflight dispatch {inflight_dispatch_id} for order {order_number}; routing to cancel logic"
            )
        else:
            # Another rider already picked this job
            logger.info(
                "Order %s already inflight with rider %s (recipient %s)",
                order_number,
                inflight_row["rider_id"],
                recipient,
            )
            await wa.send_message(
                to=recipient, text="Sorry, this job was picked up by another rider."
            )
            return

    order_status = order_status.data[0]
    await initial_handle_of_rider_response(order_status, callback_data)


# %%
IS_LOCATION_REQUEST = filters.contains("/riderLocationRequest", ignore_case=False)


async def rider_request_location(wa: WhatsApp, msg: Message):
    """
    Rider's request for location. This is a blocking operation. Entry point into the graph.
    """
    # Callback created in _send_delivery_instructions, in agent_app_handlers
    callback_data: dict = json.loads(msg.data)
    logger.info(f"callbackdata: {callback_data}")
    await run_rider_agent_w_custom_msg(
        recipient=callback_data["recipient"], human_msg=callback_data["human_msg"]
    )


# %%
IS_SHIFT_AVAILABILITY = filters.contains("/shiftAvailability", ignore_case=False)


async def handle_shift_availability(wa: WhatsApp, msg: Message):
    # Callback created in enquire_shift_availability, in wa_senders.py
    callback_data: dict = json.loads(msg.data)
    recipient = callback_data["recipient"]
    human_msg = callback_data["human_msg"]
    if human_msg == "Yes":
        await wa.send_message(
            to=recipient, text="Great! You will receive notifications for new jobs."
        )
        update_shift_status = (
            client_ordelo.table("rider_master")
            .update({"is_in_shift": True})
            .eq("rider_id", recipient)
            .execute()
        )
        logger.info(f"Started shift status for rider {recipient}")
    else:
        # Check if rider is currently on a job
        inflight_check = (
            client_ordelo.table("delivery_inflight")
            .select("order_number")
            .eq("rider_id", recipient)
            .execute()
        )
        if len(inflight_check.data) > 0:
            order_number = inflight_check.data[0]["order_number"]
            await wa.send_message(
                to=recipient,
                text=f"You are currently on a job for order {order_number}. Please complete the job first.",
            )
            logger.info(
                f"Rider {recipient} tried to end shift but is on job {order_number}"
            )
            return

        await wa.send_message(
            to=recipient,
            text="Ok. You will not receive job notifications for the next 24 hrs.",
        )
        update_shift_status = (
            client_ordelo.table("rider_master")
            .update({"is_in_shift": False})
            .eq("rider_id", recipient)
            .execute()
        )
        logger.info(f"Ended shift status for rider {recipient}")


# %%
IS_ADMIN_AVAILABILITY = filters.contains("/adminAvailability", ignore_case=False)


async def handle_admin_availability(wa: WhatsApp, msg: Message):
    # Callback created in enquire_admin_availability, in wa_senders.py
    callback_data: dict = json.loads(msg.data)
    recipient = callback_data["recipient"]
    await msg.reply(
        text="Great! You will receive notification for new orders for the next 24 hrs!"
    )
    logger.info(f"Admin availability confirmed for {recipient}")


async def _update_restaurant_order_status(order_number: str, status: str, msg: Message):
    """Background task to update restaurant order status."""
    try:
        result = await asyncio.to_thread(
            lambda: client_ordelo.table("delivery_summary")
            .update(
                {
                    "restaurant_confirmation_status": status,
                    "restaurant_admin": msg.sender,
                }
            )
            .eq("order_number", order_number)
            .eq("restaurant_confirmation_status", "restaurant_unconfirmed")
            .execute()
        )
        if result.data:
            logger.info(f"Restaurant order status updated: {order_number} -> {status}")
        else:
            await msg.reply(text="Order Already Accepted")
            logger.info(
                "Skipped restaurant order status update for %s; current status is not restaurant_unconfirmed",
                order_number,
            )
    except Exception as e:
        logger.error(
            f"Failed to update restaurant order status for {order_number}: {e}"
        )


# %% Restaurant order confirmation
IS_RESTAURANT_ORDER_ACCEPT_DECLINE = filters.contains(
    "/RestaurantOrder", ignore_case=False
)


async def restaurant_order_accept_decline_handler(wa: WhatsApp, msg: Message):
    callback_data: CallbackButtonData = CallbackButtonData(**json.loads(msg.data))
    # Callback data created in send_restaurant_order_confirmation, in utils_common.waba_utils.wa_templates.restaurant_confirmation_template

    order_number = callback_data.order_number
    order_time = callback_data.order_time
    recipient = msg.sender

    logger.info(f"Restaurant order confirmation: {order_number}")

    if "Accept" in callback_data.action:
        asyncio.create_task(
            _update_restaurant_order_status(order_number, "restaurant_accept", msg)
        )

    elif "Decline" in callback_data.action:
        asyncio.create_task(
            _update_restaurant_order_status(order_number, "restaurant_decline", msg)
        )

    return


# %% Handle pickup time selection. The pickup_time needs to be updated in delivery_summary table
IS_PICKUP_TIME = filters.contains("/PickupTime", ignore_case=False)


async def handle_pickup_time_selection(wa: WhatsApp, msg: Message):
    callback_data: CallbackButtonData = CallbackButtonData(**json.loads(msg.data))
    # Callback data created in send_pickup_time_selection, in utils_common.waba_utils.wa_senders

    order_number = callback_data.order_number
    pickup_time = callback_data.pickup_time
    recipient = msg.sender

    logger.info(
        f"Updating pickup time for order {order_number} to {pickup_time} (status -> unassigned)",
    )

    try:
        update_vals = {
            "pickup_time": pickup_time,
            "status": "unassigned",
            "restaurant_admin": recipient,
            "restaurant_update_dtts": datetime.now(timezone.utc).isoformat(),
        }
        result = await asyncio.to_thread(
            lambda: client_ordelo.table("delivery_summary")
            .update(update_vals)
            .eq("order_number", order_number)
            .eq("restaurant_confirmation_status", "restaurant_accept")
            .execute()
        )
        if result.data:
            await msg.reply(text="Pickup time updated")
            logger.info(
                "Pickup time updated for order %s to %s (status -> unassigned)",
                order_number,
                pickup_time,
            )
        else:
            await msg.reply(text="Pickup time already updated")
            logger.info(
                "Skipped pickup time update for %s; status is not restaurant_accept",
                order_number,
            )
    except Exception as e:
        logger.error(f"Failed to update pickup time for order {order_number}: {e}")


# %%
async def admin_collection_ready(
    msg: WhatsApp, callback: CallbackButton[CallbackButtonData]
):
    # Callback data created in admin_order_reciept in delivery_inflight_graph_init_hook(delivery_hooks.py)
    # ordelo_base_url = await get_restaurant_base_url_async(rest_ref="ORDELO")
    callback_data: CallbackButtonData = CallbackButtonData(**json.loads(callback.data))

    await run_rider_agent_w_custom_msg(
        recipient=callback_data.rider_id,
        human_msg=f"call `tool notify_food_ready_for_pickup`. Rider should hurry to {callback_data.restaurant_name} to pickup the food.",
    )

    # async with httpx.AsyncClient() as client:
    #     await client.post(
    #         f"{ordelo_base_url}/delivery-hooks/notify-food-ready-for-pickup/{callback_data.rider_id}",
    #         json={
    #             "restaurant_name": "Elai Salisbury",
    #             "order_number": callback_data.order_id,
    #         },
    #     )
    return
