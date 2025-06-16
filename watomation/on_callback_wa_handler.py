"""
WhatsApp callback button handler for delivery dispatch responses
    . Processes rider responses to delivery dispatch assignments
    . Validates callback data and updates delivery status
    . Integrates with OrdeloAgent delivery graph logic
    . Handles cases where jobs are no longer available
    . Provides feedback to riders about dispatch status

Key Functions:
    . dispatch_response - Main entry point for rider dispatch responses
"""

# %%
from pywa_async import WhatsApp
from config import logger
from pywa.types import Message
import json

# project modules
from ordelo.agent_app_handlers import initial_handle_of_rider_response
from config import pg_settings, client_ordelo
from ordelo.agents.agent_runner import run_rider_graph
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

    # If order is not found
    order_status = (
        client_ordelo.table("delivery_summary")
        .select("status")
        .eq("order_number", callback_data["order_number"])
        .execute()
    )

    if len(order_status.data) == 0:
        logger.error(
            "No delivery detail found for order number: {}".format(
                callback_data["order_number"]
            )
        )
        await wa.send_message(
            to=recipient, text="Sorry, This job is no longer available"
        )
        return

    # If order is rider is already inflight
    inflight = (
        client_ordelo.table("delivery_inflight")
        .select("*")
        .eq("rider_id", recipient)
        .execute()
    )
    if len(inflight.data) > 0:
        logger.info(
            "Rider is already inflight for order number: {}".format(
                callback_data["order_number"]
            )
        )
        await wa.send_message(to=recipient, text="Sorry, You are already on a job")
        return

    order_status = order_status.data[0]
    await initial_handle_of_rider_response(order_status, callback_data)


# %%
async def rider_request_location(wa: WhatsApp, msg: Message):
    """
    Rider's request for location. This is a blocking operation. Entry point into the graph.
    """

    callback_data: dict = json.loads(msg.data)
    logger.info(f"callbackdata: {callback_data}")
    await run_rider_graph(
        recipient=callback_data["recipient"], human_msg=callback_data["human_msg"]
    )
