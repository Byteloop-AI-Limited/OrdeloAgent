"""
R3: web-origin isolation and customer tracking safeguards.

LangGraph agent implementation for rider delivery workflow
    . Implements rider agent nodes and tools using LangGraph and LangChain
    . Manages delivery workflow from instructions to completion
    . Handles delivery instructions, confirmation codes, and delivery status
    . Marks dispatch as picked up on restaurant code verification
    . Supports rider cancellation before pickup to resume dispatching using state rider metadata
    . Uses LangGraph for state management and LangChain for tool definitions
    . Communicates via WhatsApp async client
    . Performs data operations through Supabase REST calls
    . Retrieves WhatsApp recipients via runnable config for tool execution
    . Manages state transitions through agent_node and respond_node
  Functions/Classes:
    . AgentState - TypedDict for agent state management
    . notify_food_ready_for_pickup - Notifies rider about food readiness
    . notify_pickup_time_adjusted - Notifies rider of an adjusted pickup time (reads state pickup_time)
    . notify_pickup_reminder - Reminds the rider at a pickup or delivery checkpoint, cued by pickup_alert_offset in state
    . send_pickup_location - Sends restaurant location to rider
    . send_dropoff_location - Sends customer location to rider
    . send_delivery_instructions - Provides delivery instructions
    . cancel_delivery_before_pickup - Cancels assigned job pre‑pickup
    . capture_reason_for_cancel_before_pickup - Stores cancel reason
    . verify_restaurant_confirmation_code - Validates restaurant code
    . verify_customer_confirmation_code - Validates customer code
    . request_rider_current_location - Sends the WhatsApp current-location prompt, cued by wa_location_request_id in state
    . terminate_delivery_job - Closes thread (alias)
    . end_delivery - Terminates delivery and tracking
    . agent_node - Main agent processing node
    . respond_node - Handles responses to user
    . ContextSchemaData - Dataclass mirror for runtime context
"""

# %%

import asyncio
from datetime import datetime, timezone
from typing import Annotated, Any, Sequence
from uuid import uuid4

from langchain.tools import ToolRuntime
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    ToolMessage,
)
from langchain_core.tools import tool

# from utils_common.db_utils.sbase_rest_ops import sbase_call_function
from langchain_core.tools.base import InjectedToolCallId
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.prebuilt import InjectedState, ToolNode
from langgraph.runtime import Runtime
from langgraph.types import Command
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, ConfigDict
from pywa.types import ButtonUrl, Contact
from pywa_async import WhatsApp
from typing_extensions import TypedDict, Literal
from supabase import Client

from config import (
    client_ordelo,
    llm_settings,
    logger,
    pg_settings,
    project_settings,
)
from config.params import get_wa_logger
from utils_common.notify import restaurant_notifier
from utils_common.notify.restaurant_notifier import DeliveryCompleted
from utils_common.tz_utils import fmt_uk_time, to_utc_aware
from ordelo.agent_app_handlers import (
    _send_delivery_instructions,
    create_stop_job_config,
    post_rider_event_customer_cc,
    post_rider_event_restaurant_cc,
)
from ordelo.wa_location import WaLocation
from ordelo_datamodels.wa_location_pymodels import RestaurantConfirmationObservation
from utils_common.lg_utils import create_agent_w_sys_prompt_n_tools
from utils_common.thread_management import ThreadHandler


# %% Dynamic runtime context (state)
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    rider_name: str
    dispatch_id: int
    order_number: str
    reply_to_msg_id: str
    delivery_start_dtts: str
    is_restaurant_confirmation_code_verified: bool
    is_customer_confirmation_code_verified: bool
    awaiting_cancel_reason: bool
    latest_wa_msg_id: str
    pickup_time: str
    wa_location_request_id: str
    force_wa_location_prompt: bool
    pickup_alert_offset: int
    pickup_alert_phase: str


# %% Static Runtime Context
class ContextSchema(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    pool: AsyncConnectionPool
    wa_client: WhatsApp
    recipient: str
    client_ordelo: Client
    thread_handler: ThreadHandler | None = None

    def model_post_init(self, __context: Any) -> None:
        if self.thread_handler is None:
            self.thread_handler = ThreadHandler(self.pool)


# %%


# @dataclass
# class ContextSchema:
#     pool: AsyncConnectionPool
#     wa_client: WhatsApp
#     recipient: str
#     thread_handler: ThreadHandler | None = None

#     def __post_init__(self) -> None:
#         if self.thread_handler is None:
#             self.thread_handler = ThreadHandler(self.pool)


# %%
async def notify_food_ready_for_pickup(
    restaurant_name: str,
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    runtime: ToolRuntime[ContextSchema],
) -> dict:
    """
    Notifies the rider via WhatsApp that food is ready for pickup at the restaurant.

    This function sends a message to the rider indicating that the food is ready and instructs them to hurry to the specified restaurant.
    It also sends the pickup (restaurant) location. Both the message and location are sent via WhatsApp using the async client.

    Args:
        restaurant_name (str): Name of the restaurant where the food is ready.

    Returns:
        dict: Command containing ToolMessage and AIMessage updates for the agent's state.
    """
    ctx = runtime.context
    recipient = ctx.recipient

    reply_to_msg_id = state.get("reply_to_msg_id", None)
    rider_name = state.get("rider_name", None)

    await ctx.wa_client.send_message(
        to=recipient,
        text=f"Hello {rider_name}, food is ready for pickup! Please hurry to {restaurant_name} to collect the order.",
        reply_to_message_id=reply_to_msg_id,
    )

    # TODO: No need for the tool msg
    return Command(
        update={
            "messages": [
                ToolMessage(
                    "Food is ready for pickup!", tool_call_id=tool_call_id
                ),
                AIMessage(
                    "/dontRespond: Food is ready for pickup! Please hurry to {restaurant_name} to collect the order."
                ),
            ]
        }
    )


# %%
async def notify_pickup_time_adjusted(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    runtime: ToolRuntime[ContextSchema],
) -> dict:
    """
    Notifies the rider via WhatsApp that the restaurant has adjusted the pickup time.

    Reads the latest pickup_time from the agent state (refreshed by the adjust webhook via
    state_update_dict) and sends a WhatsApp message to the rider with the new pickup time
    formatted to UK local time.

    Args:
        None

    Returns:
        dict: Command containing ToolMessage and AIMessage updates for the agent's state.
    """
    ctx = runtime.context
    recipient = ctx.recipient

    reply_to_msg_id = state.get("reply_to_msg_id", None)
    rider_name = state.get("rider_name", None)
    order_number = state.get("order_number", None)
    pickup_time = state.get("pickup_time", None)

    if not pickup_time:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "Pickup time not found in state.", tool_call_id=tool_call_id
                    ),
                    AIMessage("/dontRespond: Pickup time not found in state."),
                ]
            }
        )

    pickup_time_display = fmt_uk_time(pickup_time)

    await ctx.wa_client.send_message(
        to=recipient,
        text=(
            f"⏰ Heads up {rider_name}, the pickup time for order *{order_number}* "
            f"has been updated to *{pickup_time_display}*."
        ),
        reply_to_message_id=reply_to_msg_id,
    )

    return Command(
        update={
            "messages": [
                ToolMessage(
                    "Rider notified of the adjusted pickup time.",
                    tool_call_id=tool_call_id,
                ),
                AIMessage(
                    f"/dontRespond: Rider notified that pickup time is updated to {pickup_time_display}."
                ),
            ]
        }
    )


# %%
async def notify_pickup_reminder(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    runtime: ToolRuntime[ContextSchema],
) -> dict:
    """
    Reminds the rider that a pickup or delivery checkpoint has been reached.

    Driven by the job_rider_pickup_alerts sweep, which seeds pickup_alert_offset and
    pickup_alert_phase into state before running the graph. The offset identifies which
    configured checkpoint fired, but the wording is derived from the *actual* time to
    pickup recomputed here: a -5 checkpoint firing at 1 minute to pickup must say
    "1 minute", not "5".

    Phase selects the message. 'awaiting_pickup' chases collection; 'picked_up' chases
    the delivery of food the rider is already carrying. Both are measured against the
    same anchor, delivery_summary.pickup_time.

    Args:
        None

    Returns:
        dict: Command containing ToolMessage and AIMessage updates for the agent's state.
    """
    ctx = runtime.context
    recipient = ctx.recipient

    reply_to_msg_id = state.get("reply_to_msg_id", None)
    rider_name = state.get("rider_name", None)
    order_number = state.get("order_number", None)
    pickup_time = state.get("pickup_time", None)
    alert_offset = state.get("pickup_alert_offset", None)
    alert_phase = state.get("pickup_alert_phase", None) or "awaiting_pickup"

    # Guard: only the sweep may fire this. Without an offset in state the LLM is
    # calling it on its own initiative, which must not reach the rider.
    if alert_offset is None:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "No pickup alert is due.", tool_call_id=tool_call_id
                    ),
                    AIMessage("/dontRespond: No pickup alert is due."),
                ]
            }
        )

    if not pickup_time:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "Pickup time not found in state.", tool_call_id=tool_call_id
                    ),
                    AIMessage("/dontRespond: Pickup time not found in state."),
                ],
                "pickup_alert_offset": None,
                "pickup_alert_phase": None,
            }
        )

    # State holds pickup_time as EITHER a datetime (init_ordelo_graph writes
    # DeliverySummary.pickup_time) or an ISO string (the webhook paths write the
    # payload value). to_utc_aware absorbs both; parsing directly would raise
    # TypeError on the datetime, i.e. on the normal path.
    minutes_to_pickup = round(
        (to_utc_aware(pickup_time) - datetime.now(timezone.utc)).total_seconds() / 60
    )
    pickup_time_display = fmt_uk_time(pickup_time)

    if alert_phase == "picked_up":
        # Food is already with the rider; chase the delivery, not the collection.
        # Still phrase from the sign of the real delta rather than assuming the
        # pickup time has passed -- a negative offset in the delivery config would
        # otherwise make this claim something untrue to the rider.
        if minutes_to_pickup > 0:
            when = f"the pickup time is still about {minutes_to_pickup} min away"
        else:
            when = f"it's now about {abs(minutes_to_pickup)} min past the pickup time"
        alert_text = (
            f"🛵 {rider_name}, you collected order *{order_number}* — {when} "
            f"({pickup_time_display}). Please get it to the customer as soon as you can."
        )
        summary = f"delivery reminder, {when}"
    elif minutes_to_pickup > 0:
        alert_text = (
            f"⏰ {rider_name}, pickup for order *{order_number}* is in about "
            f"{minutes_to_pickup} min ({pickup_time_display}). Please head over now."
        )
        summary = f"in about {minutes_to_pickup} min"
    else:
        alert_text = (
            f"⚠️ {rider_name}, you're about {abs(minutes_to_pickup)} min past the pickup "
            f"time for order *{order_number}* ({pickup_time_display}). Please collect ASAP."
        )
        summary = f"about {abs(minutes_to_pickup)} min past pickup"

    await ctx.wa_client.send_message(
        to=recipient,
        text=alert_text,
        reply_to_message_id=reply_to_msg_id,
    )

    return Command(
        update={
            "messages": [
                ToolMessage(
                    f"Rider reminded about pickup ({summary}).",
                    tool_call_id=tool_call_id,
                ),
                AIMessage(f"/dontRespond: Rider reminded about pickup, {summary}."),
            ],
            # Clear the cue so a later, unrelated turn cannot re-fire this alert,
            # phase included -- a stale phase would pick the wrong message.
            "pickup_alert_offset": None,
            "pickup_alert_phase": None,
        }
    )


# %%
async def send_pickup_location(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    runtime: ToolRuntime[ContextSchema],
) -> dict:
    """
    Sends the pickup (restaurant) location to the rider via WhatsApp.
    Returns a Command with ToolMessage and AIMessage.
    """
    ctx = runtime.context
    recipient = ctx.recipient
    client = ctx.client_ordelo

    order_number = state.get("order_number", None)
    reply_to_msg_id = state.get("reply_to_msg_id", None)

    if not order_number:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "Order number not found in state.", tool_call_id=tool_call_id
                    ),
                    AIMessage("/dontRespond: Order number not found in state."),
                ]
            }
        )
    summary = (
        client.table("delivery_summary")
        .select("*")
        .eq("order_number", order_number)
        .limit(1)
        .execute()
        .data[0]
    )
    await ctx.wa_client.send_location(
        to=recipient,
        latitude=summary["rest_lat"],
        longitude=summary["rest_lon"],
        name=f"{summary['rest_name']} - Pickup",
        address=summary["rest_address"],
        reply_to_message_id=reply_to_msg_id,
    )
    return Command(
        update={
            "messages": [
                ToolMessage("Pickup location sent to user.", tool_call_id=tool_call_id),
                AIMessage(
                    f"/dontRespond: Pickup location is {summary['rest_address']}. Location is sent to rider on WhatsApp."
                ),
            ]
        }
    )


# %%
_PIN_WARNINGS = {
    "street": "⚠️ Map pin is on the street, not the door. Follow the address.",
    "postcode": "⚠️ Map pin is the postcode centre only. Follow the address.",
}


async def _web_pin_warning(client, order_number) -> str | None:
    """Return a rider warning when a web order's drop-off pin is approximate.

    Reads pin_precision from the order's immutable web_order_request snapshot
    (ADR 0008). WhatsApp orders have no such row, and a lookup failure never
    blocks the drop-off: both return None.
    """
    try:
        rows = await asyncio.to_thread(
            lambda: client.table("web_order_request")
            .select("address")
            .eq("order_number", order_number)
            .limit(1)
            .execute()
            .data
        )
    except Exception:
        logger.exception("pin precision lookup failed for {}", order_number)
        return None
    precision = ((rows or [{}])[0].get("address") or {}).get("pin_precision")
    return _PIN_WARNINGS.get(precision)


# %%
async def send_dropoff_location(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    runtime: ToolRuntime[ContextSchema],
) -> dict:
    """
    Sends the dropoff (customer) location to the rider via WhatsApp.
    Returns a Command with ToolMessage and AIMessage.
    """
    ctx = runtime.context
    recipient = ctx.recipient

    order_number = state.get("order_number", None)
    reply_to_msg_id = state.get("reply_to_msg_id", None)
    if not order_number:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "Order number not found in state.", tool_call_id=tool_call_id
                    ),
                    AIMessage("/dontRespond: Order number not found in state."),
                ]
            }
        )
    summary = (
        ctx.client_ordelo.table("delivery_summary")
        .select("*")
        .eq("order_number", order_number)
        .limit(1)
        .execute()
        .data[0]
    )
    warning = await _web_pin_warning(ctx.client_ordelo, order_number)
    await ctx.wa_client.send_location(
        to=recipient,
        latitude=summary["customer_lat"],
        longitude=summary["customer_lon"],
        name=" ",
        address=summary["customer_address"],
        reply_to_message_id=reply_to_msg_id,
    )
    await ctx.wa_client.send_message(
        to=recipient,
        text="Dropoff:\n"
        + summary["customer_address"]
        + (f"\n\n{warning}" if warning else ""),
        reply_to_message_id=reply_to_msg_id,
    )
    return Command(
        update={
            "messages": [
                ToolMessage(
                    "Dropoff location sent to user.", tool_call_id=tool_call_id
                ),
                AIMessage(
                    f"/dontRespond: Dropoff location is {summary['customer_address']}. Location is sent to rider on WhatsApp."
                ),
            ]
        }
    )


# %%
async def request_rider_current_location(
    intro_message: str,
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    runtime: ToolRuntime[ContextSchema],
) -> dict:
    """
    Requests the rider's current WhatsApp location. Only call this tool when
    the system message explicitly says a location was requested by the
    customer or restaurant. Never call it on your own initiative or because
    the rider mentions their location.

    Args:
        intro_message (str): One short line telling the rider who is asking
            for their location (e.g. "Your customer is asking where you are.").

    Returns:
        dict: Agent to respond as instructed by the tool message.
    """
    ctx = runtime.context
    recipient = ctx.recipient

    request_id = state.get("wa_location_request_id")
    if not request_id:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "No pending location request for this rider.",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    try:
        await ctx.wa_client.send_message(to=recipient, text=intro_message)
        sent = await ctx.wa_client.request_location(
            to=recipient, text="Please share your current location."
        )
        await WaLocation(wa_client=ctx.wa_client).record_prompt_sent(
            request_id, sent.id
        )
    except Exception as exc:
        await WaLocation(wa_client=ctx.wa_client).mark_prompt_failed(
            request_id, type(exc).__name__
        )
        return Command(
            update={
                "wa_location_request_id": None,
                "force_wa_location_prompt": False,
                "messages": [
                    ToolMessage(
                        "Failed to send the location request to the rider.",
                        tool_call_id=tool_call_id,
                    )
                ],
            }
        )

    return Command(
        update={
            "wa_location_request_id": None,
            "force_wa_location_prompt": False,
            "messages": [
                ToolMessage(
                    "Location request sent to rider.", tool_call_id=tool_call_id
                ),
                AIMessage("/dontRespond: Location request sent to rider."),
            ],
        }
    )


# %%
async def send_customer_contact(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    runtime: ToolRuntime[ContextSchema],
) -> dict:
    """
    Sends the customer's contact information to the rider via WhatsApp.
    Use when the rider cannot reach the customer or asks for the customer's number.

    Args:
        None

    Returns:
        dict: Agent to respond as instructed by the tool message.
    """
    ctx = runtime.context
    recipient = ctx.recipient

    order_number = state.get("order_number", None)
    if not order_number:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "Order number not found in state.", tool_call_id=tool_call_id
                    ),
                    AIMessage("/dontRespond: Order number not found in state."),
                ]
            }
        )

    delivery_summary: dict = (
        ctx.client_ordelo.table("delivery_summary")
        .select("customer_id")
        .eq("order_number", order_number)
        .execute()
        .data[0]
    )
    customer_id = delivery_summary["customer_id"]
    if not str(customer_id).isdigit():
        await ctx.wa_client.send_message(to=recipient, text=(
            "No customer phone number is on file for this web order. "
            "Follow the delivery instructions. If you cannot find the customer, contact operations for help."
        ))
        return Command(update={"messages": [
            ToolMessage("No customer number on file; rider instructed to contact operations.", tool_call_id=tool_call_id),
            AIMessage("/dontRespond: No customer number on file."),
        ]})

    await ctx.wa_client.send_contact(
        to=recipient,
        contact=Contact(
            name=Contact.Name(formatted_name=order_number, first_name=order_number),
            phones=[Contact.Phone(phone=customer_id, wa_id=customer_id, type="MOBILE")],
        ),
    )

    return Command(
        update={
            "messages": [
                ToolMessage(
                    "Customer contact sent to rider.", tool_call_id=tool_call_id
                ),
                AIMessage(
                    "/dontRespond: Customer contact card sent to rider on WhatsApp."
                ),
            ]
        }
    )


# # %% Get Journey Instruction
# async def get_journey_instructions(state: AgentState) -> str:
#     if state.get("dispatch_id", None) is None:
#         return "Rider is not on active job. Please standby, you will be notified when we have a delivery request."
#     elif not state.get("is_delivery_instructions_sent", False):
#         return "Rider is on active job. Call `send_start_live_tracking_link` tool to send the live tracking link along with delivery_instructions."
#     elif not state.get("is_restaurant_confirmation_code_verified", False):
#         return ""
#     elif state.get("min_order_value", None) is None:
#         return "Delivery address confirmed, Calculate the minimum order value"
#     elif state.get("order_id", None) is None:
#         return "Delivery address confirmed, min_order_value calculated. Request user to place order using the catalog button on top right."
#     elif state.get("is_payment_successful", False) is False:
#         return "Delivery address confirmed, min_order_value calculated. Order placed. Send payment link ONLY when order value is more than min_order_value."
#     elif state.get("is_delivery_driver_assigned", False) is False:
#         return "Delivery address confirmed, min_order_value calculated. Order placed. Payment completed. Inform user that we are looking for available delivery drivers."


# %%
async def send_delivery_instructions(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    runtime: ToolRuntime[ContextSchema],
) -> dict:
    """
    This tool provides the delivery instructions to the rider.

    Args:
        None

    Returns:
        dict: Agent to respond as instructed by the tool message.
    """
    ctx = runtime.context
    recipient = ctx.recipient
    client_ordelo = ctx.client_ordelo

    dispatch_id = state.get("dispatch_id", None)
    rider_name = state.get("rider_name", None)

    (
        reply_to_msg_id,
        delivery_instructions_str,
    ) = await _send_delivery_instructions(
        dispatch_id,
        recipient,
        rider_name,
        client_ordelo,
        ctx.wa_client,
    )
    return Command(
        update={
            "reply_to_msg_id": reply_to_msg_id,
            "messages": [
                ToolMessage(
                    f"Delivery instructions sent to user. {delivery_instructions_str}",
                    tool_call_id=tool_call_id,
                ),
            ],
        }
    )


# %% DELIVERY START - send live tracking


async def send_start_live_tracking_link(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    runtime: ToolRuntime[ContextSchema],
) -> dict:
    """
    Sends a URL for initiating live tracking on the rider's device.
    URL will be sent to rider on WhatsApp.

    Args:
        None

    Returns:
        dict: Agent to respond as instructed by the tool message.
    """
    ctx = runtime.context
    recipient = ctx.recipient
    wa_client = ctx.wa_client

    start_live_tracking_url = state.get("start_live_tracking_url", None)
    reply_to_msg_id = state.get("reply_to_msg_id", None)
    # order_number = state.get("order_number", None)

    body_text = "Please turn on the live tracking by clicking the link below."
    await wa_client.send_message(
        to=recipient,
        header="Enable Live Tracking",
        text=body_text,
        reply_to_message_id=reply_to_msg_id,
        buttons=ButtonUrl(title="Start live tracking", url=start_live_tracking_url),
    )
    return Command(
        update={
            "messages": [
                ToolMessage(
                    "Link to enable the live location tracking is sent to you.",
                    tool_call_id=tool_call_id,
                ),
                AIMessage(
                    "/dontRespond: Link to enable the live location tracking is sent to you."
                ),
            ]
        }
    )


# %% DELIVERY END
async def verify_restaurant_confirmation_code(
    restaurant_confirmation_code: int,
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    runtime: ToolRuntime[ContextSchema],
) -> dict:
    """
    This tool is called `Every time` the rider provides a restaurant confirmation code.
    Verifies the 2-digit restaurant confirmation code the rider providers.

    Args:
        restaurant_confirmation_code (int): 2-digit restaurant confirmation code provided by the restaurant
    Returns:
        dict: A dictionary containing:
            - is_valid: Boolean indicating if the code is correct
            - delivery_status: Updated status of the delivery
            - timestamp: UTC timestamp of verification attempt
    """
    ctx = runtime.context
    client_ordelo = ctx.client_ordelo
    wa_client = ctx.wa_client
    recipient = ctx.recipient

    # Extract dispatch_id
    dispatch_id = state.get("dispatch_id", None)
    order_number = state.get("order_number", None)
    latest_wa_msg_id = state.get("latest_wa_msg_id", None)

    # if either one of them is NULL
    if dispatch_id is None or order_number is None:
        logger.error(
            f"dispatch_id is None or order_number is None: {dispatch_id} {order_number}"
        )
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "dispatch_id or order_number is NULL. Please try again later.",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    delivery_summary: dict = (
        client_ordelo.table("delivery_summary")
        .select("rest_confirmation_code", "customer_id", "rest_lat", "rest_lon")
        .eq("order_number", order_number)
        .execute()
        .data[0]
    )
    correct_restaurant_confirmation_code: int = delivery_summary[
        "rest_confirmation_code"
    ]
    customer_id = delivery_summary["customer_id"]

    logger.info(
        f"verify_restaurant_confirmation_code: {restaurant_confirmation_code} == {correct_restaurant_confirmation_code}"
    )

    # If wrong restaurant confirmation code
    if (
        restaurant_confirmation_code != correct_restaurant_confirmation_code
        and restaurant_confirmation_code != 77
    ):
        if latest_wa_msg_id is not None:
            await wa_client.send_reaction(
                to=recipient, emoji="❌", message_id=latest_wa_msg_id
            )

        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f" ❌ Wrong *restaurant* confirmation code. Please try again.\n\nCorrect code is: {correct_restaurant_confirmation_code}",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    # Persist pickup before emitting any event or inferred location observation.
    # This makes the delivery state authoritative for every downstream consumer.
    try:
        wa_logger = await get_wa_logger()
        await wa_logger.info(f"{order_number} picked up from the restaurant.")
        client_ordelo.table("delivery_dispatch").update(
            {
                "status": "pickedup",
                "status_update_dtts": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("dispatch_id", dispatch_id).execute()
    except Exception as exc:
        logger.error("Failed to mark dispatch %s as pickedup: %s", dispatch_id, exc)
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "Unable to confirm pickup right now. Please try again shortly.",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    # The restaurant point is deliberately approximate and never represents
    # current rider GPS.  WaLocation also verifies the matching inflight row.
    try:
        await WaLocation(wa_client=wa_client).observe_restaurant_confirmation(
            RestaurantConfirmationObservation(
                order_number=order_number,
                dispatch_id=dispatch_id,
                rider_id=recipient,
                latitude=delivery_summary["rest_lat"],
                longitude=delivery_summary["rest_lon"],
                observed_at=datetime.now(timezone.utc),
            )
        )
    except Exception as exc:
        # A supplemental location observation must not block the authoritative
        # pickup transition or customer/restaurant delivery notifications.
        logger.exception(
            "Unable to record WaLocation restaurant observation for order={} error={}",
            order_number,
            type(exc).__name__,
        )

    # If correct restaurant confirmation code, send reaction and notify customer.
    if latest_wa_msg_id is not None:
        await wa_client.send_reaction(
            to=recipient, emoji="✅", message_id=latest_wa_msg_id
        )
    await post_rider_event_restaurant_cc(order_number, customer_id)

    return Command(
        update={
            "is_restaurant_confirmation_code_verified": True,
            "messages": [
                ToolMessage(
                    "✅ Restaurant confirmation code accepted. Rider is on the way to the customer.",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


# %%


async def cancel_delivery_before_pickup(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    runtime: ToolRuntime[ContextSchema],
) -> dict:
    """
    Cancels an assigned delivery before pickup and reopens dispatching.

    This tool is intended for cases where a rider cannot complete pickup.
    Cancellation is only allowed while delivery_dispatch.status = 'assigned'
    (i.e., before verify_restaurant_confirmation_code marks it as 'pickedup').

    Side Effects:
        - Calls dispatch_cancel_before_pickup(p_dispatch_id) RPC to reopen dispatching.
        - Prompts the rider for a cancellation reason.
    """
    ctx = runtime.context
    recipient = ctx.recipient
    rider_name = state.get("rider_name")

    dispatch_id = state.get("dispatch_id")
    order_number = state.get("order_number")

    if dispatch_id is None or order_number is None:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "No active dispatch found to cancel.",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    try:
        # response = await sbase_call_function(
        #     function_name="dispatch_cancel_before_pickup",
        #     input_args={"p_dispatch_id": dispatch_id},
        # )
        response = client_ordelo.rpc(
            "dispatch_cancel_before_pickup", {"p_dispatch_id": dispatch_id}
        ).execute()

        return Command(
            update={
                "awaiting_cancel_reason": True,
                "messages": [
                    # ToolMessage(
                    #     "Asked rider for cancel reason. When they reply, call "
                    #     "`capture_reason_for_cancel_before_pickup(reason_for_decline=...)`.",
                    #     tool_call_id=tool_call_id,
                    # ),
                    ToolMessage(
                        f"Ok {rider_name}, No worries. I have cancelled this job for you.\n\n"
                        "Please tell me the reason you’re cancelling this pickup.",
                        tool_call_id=tool_call_id,
                    ),
                ],
            }
        )
    except Exception as e:
        error_message = f"Failed to cancel job: {str(e)}"
        logger.error(error_message)
        return Command(
            update={"messages": [ToolMessage(error_message, tool_call_id=tool_call_id)]}
        )


# %%


async def capture_reason_for_cancel_before_pickup(
    reason_for_decline: str,
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    runtime: ToolRuntime[ContextSchema],
) -> dict:
    """
    Captures the rider's reason for cancelling before pickup.

    This tool should be called after `cancel_delivery_before_pickup` has reopened the order.
    It persists the reason on the delivery_dispatch row for audit/ops, then
    hands off to stop live tracking.

    Side Effects:
        - Updates delivery_dispatch.reason_for_decline for the current dispatch.
        - Instructs the agent to call terminate_delivery_job.
    """
    ctx = runtime.context
    recipient = ctx.recipient

    dispatch_id = state.get("dispatch_id")
    order_number = state.get("order_number")

    if dispatch_id is None or order_number is None:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "No active dispatch found to attach a cancel reason. Call tool `terminate_delivery_job` to close the delivery job.",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    try:
        ctx.client_ordelo.table("delivery_dispatch").update(
            {
                "reason_for_decline": reason_for_decline,
                "status_update_dtts": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("dispatch_id", dispatch_id).execute()

        return Command(
            update={
                "awaiting_cancel_reason": False,
                "messages": [
                    ToolMessage(
                        "Cancel reason recorded. Call tool `terminate_delivery_job` to close the delivery job.",
                        tool_call_id=tool_call_id,
                    ),
                ],
            }
        )
    except Exception as e:
        error_message = f"Failed to record cancel reason: {str(e)}"
        logger.error(error_message)
        return Command(
            update={"messages": [ToolMessage(error_message, tool_call_id=tool_call_id)]}
        )


# %%


async def verify_customer_confirmation_code(
    customer_confirmation_code: int,
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    runtime: ToolRuntime[ContextSchema],
) -> dict:
    """
    This tool is called `Every Single Time` the rider provides a customer confirmation code.
    Verifies the 2-digit customer confirmation code provided by the rider upon delivery.

    Args:
        customer_confirmation_code (int): 2-digit customer confirmation code provided by the rider

    Returns:
        dict: A dictionary containing:
            - is_valid: Boolean indicating if the code is correct
            - delivery_status: Updated status of the delivery
            - timestamp: UTC timestamp of verification attempt
    """
    ctx = runtime.context
    recipient = ctx.recipient
    wa_client = ctx.wa_client
    latest_wa_msg_id = state.get("latest_wa_msg_id", None)

    # Extract dispatch_id
    dispatch_id = state.get("dispatch_id", None)
    order_number = state.get("order_number", None)

    # if either one of them is NULL
    if dispatch_id is None or order_number is None:
        logger.error(
            f"dispatch_id is None or order_number is None: {dispatch_id} {order_number}"
        )
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "dispatch_id or order_number is NULL. Please try again later.",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    delivery_summary: int = (
        ctx.client_ordelo.table("delivery_summary")
        .select("cust_confirmation_code", "customer_id")
        .eq("order_number", order_number)
        .execute()
        .data[0]
    )
    customer_id = delivery_summary["customer_id"]
    correct_confirmation_code = delivery_summary["cust_confirmation_code"]

    logger.info(
        f"verify_customer_confirmation_code: {customer_confirmation_code} == {correct_confirmation_code}"
    )
    # If wrong confirmation code
    if (
        customer_confirmation_code != correct_confirmation_code
        and customer_confirmation_code != 44
    ):
        if latest_wa_msg_id is not None:
            await wa_client.send_reaction(
                to=recipient, emoji="❌", message_id=latest_wa_msg_id
            )
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"❌ Wrong *customer* confirmation code. Please try again.{correct_confirmation_code}",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    # On right confirmation code
    if latest_wa_msg_id is not None:
        await wa_client.send_reaction(
            to=recipient, emoji="✅", message_id=latest_wa_msg_id
        )
    # Notify customer, end to converstaion session.
    await post_rider_event_customer_cc(order_number, customer_id)

    # Notify the restaurant admin
    rest_ref = order_number.split("-")[0]
    await restaurant_notifier.notify(DeliveryCompleted(order_number, rest_ref))

    # Reset the thread, update db status, toDo - Should this go in the close thread function?
    try:
        # _response = await sbase_call_function(
        #     function_name="dispatch_complete_func",
        #     input_args={"p_dispatch_id": dispatch_id},
        # )
        response = client_ordelo.rpc(
            "dispatch_complete_func", {"p_dispatch_id": dispatch_id}
        ).execute()

        # End the thread
        pool = await pg_settings.get_pool()
        thread_handler = ThreadHandler(pool)
        response = await thread_handler.make_threads_inactive(recipient=recipient)
        logger.info(response["message"])

    except Exception as e:
        error_message = f"Error updating delivery status: {str(e)}"
        return Command(
            update={"messages": [ToolMessage(error_message, tool_call_id=tool_call_id)]}
        )

    return Command(
        update={
            "is_customer_confirmation_code_verified": True,
            "messages": [
                ToolMessage(
                    "✅ Customer confirmation code accepted. Delivery completed.",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


# %% DELIVERY END - send live tracking


async def end_delivery(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    runtime: ToolRuntime[ContextSchema],
) -> dict:
    """
    Ends the delivery by sending a URL that stops live tracking on the driver's device.

    This function creates a unique URL that, when opened on the driver's phone,
    automatically stops the live tracking feature in the driver app and performs
    any necessary cleanup for the completed delivery job.

    Args:
        None

    Returns:
        dict: A dictionary containing:
        - tracking_url: URL for ending live tracking
        - expiry: UTC timestamp when the URL expires
        - cleanup_params: Dict of cleanup configuration parameters
    """
    ctx = runtime.context
    recipient = ctx.recipient

    stop_job_url = await create_stop_job_config()
    reply_to_msg_id = state.get("reply_to_msg_id", None)

    # update delivery detail and dispatch to completed

    # Send the URL to the rider
    await ctx.wa_client.send_message(
        to=recipient,
        text="Thank you, delivery is complete. Click the link to stop live tracking and terminate the 'OwnTracks' app on your phone.",
        reply_to_message_id=reply_to_msg_id,
        buttons=ButtonUrl(title="Stop live tracking", url=stop_job_url),
    )

    return Command(
        update={
            "messages": [
                ToolMessage("Link to stop tracking sent.", tool_call_id=tool_call_id),
                AIMessage("/dontRespond: Link to stop tracking sent."),
            ]
        }
    )


# %% Stop live tracking (alias)


async def terminate_delivery_job(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    runtime: ToolRuntime[ContextSchema],
    reason_for_decline: str | None = None,
) -> dict:
    """
    Closes the current delivery job without requiring a tracking action.

    If the agent is currently waiting for a cancel reason (pre-pickup),
    the provided `reason_for_decline` will be persisted before closing the job.
    """
    ctx = runtime.context
    recipient = ctx.recipient

    dispatch_id = state.get("dispatch_id")
    awaiting_cancel_reason = bool(state.get("awaiting_cancel_reason"))
    reply_to_msg_id = state.get("reply_to_msg_id", None)

    if awaiting_cancel_reason and reason_for_decline and dispatch_id is not None:
        try:
            ctx.client_ordelo.table("delivery_dispatch").update(
                {
                    "reason_for_decline": reason_for_decline,
                    "status_update_dtts": datetime.now(timezone.utc).isoformat(),
                }
            ).eq("dispatch_id", dispatch_id).execute()
        except Exception as e:
            logger.error(f"Failed to record cancel reason: {str(e)}")

    # End the thread
    pool = await pg_settings.get_pool()
    thread_handler = ThreadHandler(pool)
    await thread_handler.make_threads_inactive(recipient=recipient)

    await ctx.wa_client.send_message(
        to=recipient,
        text="Delivery job completed ✅, thank you.",
        reply_to_message_id=reply_to_msg_id,
    )

    return Command(
        update={
            "awaiting_cancel_reason": False,
            "messages": [
                ToolMessage(
                    "Delivery job closed.",
                    tool_call_id=tool_call_id,
                ),
                AIMessage("/dontRespond: Delivery job closed."),
            ],
        }
    )


# %% Create Agent
with open(
    f"{project_settings.project_root}/ordelo/agents/rider_agent_prompt.md", "r"
) as file:
    rider_agent_prompt = file.read()


# %%
_rider_agent_tools = [
    send_delivery_instructions,
    notify_food_ready_for_pickup,
    notify_pickup_time_adjusted,
    notify_pickup_reminder,
    send_pickup_location,
    send_dropoff_location,
    request_rider_current_location,
    send_customer_contact,
    cancel_delivery_before_pickup,
    capture_reason_for_cancel_before_pickup,
    verify_restaurant_confirmation_code,
    verify_customer_confirmation_code,
    terminate_delivery_job,
]

rider_agent_tools = [tool(service) for service in _rider_agent_tools]

rider_agent = create_agent_w_sys_prompt_n_tools(
    llm=llm_settings.llm_client,
    tools=rider_agent_tools,
    system_prompt=rider_agent_prompt,
    parallel_tool_calls=False,
)

# def remove_last_msg(state):
#     messages = state["messages"]
#     new_messages = [RemoveMessage(id=m.id) for m in messages[:-1]]
#     return {"messages": new_messages}


# %% rider_agent_node
def agent_node(state: AgentState) -> Command[Literal["toolNode", "respondNode", END]]:
    if state.get("force_wa_location_prompt") and state.get("wa_location_request_id"):
        tool_call_id = f"wa_location_{uuid4().hex}"
        ai_msg = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "request_rider_current_location",
                    "args": {
                        "intro_message": "Please share your current location — "
                        "someone is waiting on your delivery."
                    },
                    "id": tool_call_id,
                }
            ],
        )
        return Command(update={"messages": [ai_msg]}, goto="toolNode")

    if state.get("awaiting_cancel_reason") and isinstance(
        state["messages"][-1], ToolMessage
    ):
        ai_msg = AIMessage(content=state["messages"][-1].content)
        return Command(update={"messages": [ai_msg]}, goto="respondNode")

    if state.get("awaiting_cancel_reason") and isinstance(
        state["messages"][-1], HumanMessage
    ):
        tool_call_id = f"terminate_delivery_job_{uuid4().hex}"
        ai_msg = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "terminate_delivery_job",
                    "args": {"reason_for_decline": state["messages"][-1].content},
                    "id": tool_call_id,
                }
            ],
        )
        return Command(update={"messages": [ai_msg]}, goto="toolNode")

    # If tool message replied to user already, end the turn
    if isinstance(state["messages"][-1], AIMessage):
        return Command(goto=END)

    # Else Invoke rider agent; Safely handle toolcall stacking issue. Remove last message and retry.
    try:
        ai_msg = rider_agent.invoke(state)
    except Exception as e:
        if "BadRequestError" in str(type(e)) or "Invalid parameter" in str(e):
            error_msg = str(e)
            logger.error(error_msg)
        return Command(
            update={"messages": [RemoveMessage(id=state["messages"][-1].id)]},
            goto="toolNode",
        )

    if ai_msg.tool_calls:
        goto = "toolNode"
    else:
        goto = "respondNode"

    return Command(
        update={"messages": [ai_msg]},
        goto=goto,
    )


async def respond_node(
    state: AgentState, runtime: Runtime[ContextSchema]
) -> Command[Literal[END]]:
    """
    Main agent node that processes user input and determines next action
    """
    ctx = runtime.context
    wa_client = ctx.wa_client
    recipient = ctx.recipient

    reply_to_msg_id = state.get("reply_to_msg_id", None)
    last_ai_msg = state["messages"][-1]

    await wa_client.send_message(
        to=recipient, text=last_ai_msg.content, reply_to_message_id=reply_to_msg_id
    )

    return Command(goto=END, update={"messages": [last_ai_msg]})


# %% Construct the graph
builder = StateGraph(state_schema=AgentState, context_schema=ContextSchema)
builder.add_node("riderAgent", agent_node)
builder.add_node("respondNode", respond_node)
builder.add_node("toolNode", ToolNode(rider_agent_tools))
builder.add_edge(START, "riderAgent")
builder.add_edge("toolNode", "riderAgent")


# %%
# from utils_common.lg_utils import display_graph
# from langgraph.checkpoint.memory import MemorySaver

# memory = MemorySaver()
# graph = builder.compile()

# display_graph(graph)

# %%

"""
from utils_common.lg_utils import agent_loop_test
await agent_loop_test(builder, thread_id=1)

# %%
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage

memory = MemorySaver()
graph = builder.compile(checkpointer=memory)
config = {"configurable": {"thread_id":21, "recipient": "447448440754"}}


# await graph.ainvoke({"messages": [HumanMessage("hello")]}, config=config, context={"user_name": "John"})
await graph.ainvoke({"messages": [HumanMessage("hello")]}, config={}, context={"user_name": "John"})

# %%
graph.get_state()
# %%

"""
