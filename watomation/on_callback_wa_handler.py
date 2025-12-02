"""
WhatsApp callback button handler for delivery dispatch responses
    . Processes rider responses to delivery dispatch assignments
    . Validates callback data and updates delivery status
    . Integrates with OrdeloAgent delivery graph logic
    . Handles cases where jobs are no longer available
    . Provides feedback to riders about dispatch status
    . Checks for existing inflight deliveries to prevent conflicts
    . Serves as entry point into the LangGraph agent workflow
    . Processes restaurant confirmation of food preparation time
    . Uses asyncio.create_task for long-running RPC calls to avoid timeouts
  Functions/Classes:
    . dispatch_response - Processes rider responses to delivery dispatch assignments
    . rider_request_location - Handles rider requests for location information
    . handle_shift_availability - Handles rider shift availability responses
    . handle_restaurant_confirmation - Processes restaurant prep time confirmation
    . restaurant_order_accept_decline_handler - Handles restaurant accept/decline responses
    . _update_restaurant_order_status - Background task for updating restaurant order status
"""

# %%
import asyncio
from pywa_async import WhatsApp
from config import logger
from pywa.types import Message
import json

# project modules
from ordelo.agent_app_handlers import initial_handle_of_rider_response
from config import pg_settings, client_ordelo, client
from ordelo.agents.agent_runner import run_rider_graph
from utils_common.waba_utils.wa_senders import CallbackButtonData
from utils_common.waba_utils.wa_senders import send_restaurant_pickup_time
from pywa.types import CallbackButton
# %%


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
            # Same rider is already on this job
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
async def rider_request_location(wa: WhatsApp, msg: Message):
    """
    Rider's request for location. This is a blocking operation. Entry point into the graph.
    """
    # Callback created in _send_delivery_instructions, in agent_app_handlers
    callback_data: dict = json.loads(msg.data)
    logger.info(f"callbackdata: {callback_data}")
    await run_rider_graph(
        recipient=callback_data["recipient"], human_msg=callback_data["human_msg"]
    )


# %%
async def handle_shift_availability(wa: WhatsApp, msg: Message):
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


# %% Handle pickup time selection. The pickup_time needs to be updated in delivery_summary table
def handle_pickup_time_selection(wa: WhatsApp, msg: Message):
    callback_data: CallbackButtonData = CallbackButtonData(**json.loads(msg.data))
    # Callback data created in send_pickup_time_selection, in utils_common.waba_utils.wa_senders

    order_number = callback_data.order_number
    pickup_time = callback_data.pickup_time
    recipient = msg.sender

    logger.info(f"Updating pickup time for order {order_number} to {pickup_time}")

    # Update the pickup time in delivery_summary table, status='unassigned'
    client_ordelo.table("delivery_summary").update(
        {"pickup_time": pickup_time, "status": "unassigned"}
    ).eq("order_number", order_number).eq("status", "restaurant_accept").execute()


async def _update_restaurant_order_status(order_number: str, status: str):
    """Background task to update restaurant order status."""
    try:
        await asyncio.to_thread(
            lambda: client.table("delivery_summary")
            .update({"status": status})
            .eq("order_number", order_number)
            .execute()
        )
        logger.info(f"Restaurant order status updated: {order_number} -> {status}")
    except Exception as e:
        logger.error(
            f"Failed to update restaurant order status for {order_number}: {e}"
        )


# %% Restaurant order confirmation
async def restaurant_order_accept_decline_handler(wa: WhatsApp, msg: Message):
    callback_data: CallbackButtonData = CallbackButtonData(**json.loads(msg.data))
    # Callback data created in send_restaurant_order_confirmation, in utils_common.waba_utils.wa_templates.restaurant_confirmation_template

    order_number = callback_data.order_number
    order_time = callback_data.order_time
    recipient = msg.sender

    logger.info(f"Restaurant order confirmation: {order_number}")

    if "Accept" in callback_data.action:
        asyncio.create_task(
            _update_restaurant_order_status(order_number, "restaurant_accept")
        )

    elif "Decline" in callback_data.action:
        asyncio.create_task(
            _update_restaurant_order_status(order_number, "restaurant_decline")
        )

    return


# %% Restaurant order confirmation


async def handle_restaurant_confirmation(wa: WhatsApp, msg: Message):
    """
    Handles restaurant confirmation callback from WhatsApp buttons.

    Callback data structure:
    {
        "command": "/restaurantConfirmation",
        "order_number": "REST-12345",
        "prep_time_minutes": 15
    }
    """
    try:
        sender = msg.sender
        callback_data: CallbackButtonData = json.loads(msg.data)

        order_number = callback_data.get("order_number")
        prep_time_minutes = callback_data.get("prep_time_minutes")

        logger.info(
            f"Restaurant confirmation received: order={order_number}, prep_time={prep_time_minutes}min, sender={sender}"
        )

        # Send immediate confirmation to restaurant
        await wa.send_message(
            to=sender,
            text=f"✅ Confirmed! Food will be ready in {prep_time_minutes} minutes.\n\nDriver will be dispatched accordingly.",
        )
        logger.info(
            f"Restaurant confirmation received: {prep_time_minutes}min for order {order_number}"
        )

        # Call database function to update as background task to avoid timeout
        async def _handle_confirmation():
            try:
                result = await asyncio.to_thread(
                    lambda: client_ordelo.rpc(
                        "handle_restaurant_confirmation",
                        {
                            "p_order_number": order_number,
                            "p_prep_time_minutes": prep_time_minutes,
                        },
                    ).execute()
                )
                logger.info(
                    f"Restaurant confirmation processed for order {order_number}: {result.data}"
                )
            except Exception as e:
                logger.error(
                    f"Background task failed for restaurant confirmation {order_number}: {e}"
                )

        asyncio.create_task(_handle_confirmation())

    except Exception as e:
        logger.error(f"Error handling restaurant confirmation: {e}")
        await wa.send_message(
            to=msg.sender,
            text="❌ Error processing confirmation. Please contact support.",
        )
