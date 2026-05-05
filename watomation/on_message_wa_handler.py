"""
WhatsApp message handler for Ordelo delivery system
    . Processes incoming WhatsApp messages from riders and customers
    . Handles command parsing and execution for delivery operations
    . Manages live location sharing and tracking
    . Provides delivery status updates and notifications
    . Integrates with OrdeloAgent for delivery workflow orchestration
    . Supports command-based interactions for delivery management
    . Handles error cases and provides appropriate responses
    . Uses asyncio.create_task for long-running RPC calls to avoid timeouts
  Functions/Classes:
    . process_wa_msg - Main entry point for WhatsApp message processing
    . live_location - Handles live location updates from riders
    . reset_thread - Resets conversation thread state
    . test_delivery - Creates test delivery for debugging
    . init_delivery_summary - Background task for initializing delivery via RPC
    . handle_rider_command - Processes commands from delivery riders
    . clear_dispatch - Clears active dispatch assignments
    . send_live_map_location - Shares live location map with rider
    . handle_callback_button - Handles rider responses to dispatches
"""

# %%
import asyncio
from datetime import datetime, timezone
from typing import Literal
from utils_common.tz_utils import UK_TZ

from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel
from pywa.types import FlowButton, Message
from pywa.types.flows import FlowActionType, FlowRequest, FlowResponse
from pywa_async import WhatsApp, filters, types

from config import (
    _sync_wa_client,
    client_ordelo,
    llm_settings,
    logger,
    pg_settings,
    client_ordelo,
)
from ordelo.agent_app_handlers import (
    # enquire_shift_availability_non_template,
    get_live_map_location_url,
)
from utils_common.waba_utils.wa_senders import enquire_shift_availability_non_template
from ordelo.agents.agent_runner import run_rider_agent_w_custom_msg
from utils_common.db_utils.sbase_pool_ops import execute_sql_query
from config.params import get_restaurant_base_url_async

# project modules
# from utils_common.db_utils.sbase_rest_ops import sbase_get
from utils_common.thread_management import ThreadHandler

# %% Intent Classifier


class RiderShiftIntent(BaseModel):
    """Structured response for rider shift intent classification"""

    intent: Literal["End Shift", "SomethingElse"]
    confidence: float


llm = llm_settings.llm_client


def get_rider_intent(message: str) -> RiderShiftIntent:
    prompt = f"""
    Classify the intent of the following message from delivery rider. Determine if the rider wants to "End Shift" or if it's "SomethingElse".
    message: {message}
    """
    structured_llm = llm.with_structured_output(RiderShiftIntent)
    response = structured_llm.invoke(prompt)
    return response


# %% After-hours guard


def _message_time_uk(msg: Message) -> datetime | None:
    ts = getattr(msg, "timestamp", None) or getattr(msg, "timestamp_ms", None)
    if ts is None:
        return None

    # If we already have a datetime, convert directly.
    if isinstance(ts, datetime):
        dt_utc = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        return dt_utc.astimezone(UK_TZ)

    # Otherwise coerce to float timestamp.
    try:
        ts_val = float(ts)
    except (TypeError, ValueError):
        return None

    if ts_val > 1_000_000_000_000:  # likely milliseconds
        ts_val = ts_val / 1000
    try:
        utc_time = datetime.fromtimestamp(ts_val, tz=timezone.utc)
    except (OSError, ValueError):
        return None
    return utc_time.astimezone(UK_TZ)


def is_outside_service_hours(_: WhatsApp, msg: Message) -> bool:
    msg_time = _message_time_uk(msg)
    if msg_time is None:
        return False
    return not (9 <= msg_time.hour < 23)


OUT_OF_HOURS_FILTER = filters.new(is_outside_service_hours)


async def send_closed_message(wa: WhatsApp, msg: Message):
    await wa.send_message(
        to=msg.sender,
        text="Thank you for your message. We are currently closed. Try again during our service hours (11am-9pm).",
    )


# %% Run graph on msg
async def process_wa_msg(wa: WhatsApp, msg: Message):
    await msg.indicate_typing()
    pool: AsyncConnectionPool = await pg_settings.get_pool()
    recipient = msg.sender
    thread_handler = ThreadHandler(pool)

    thread_row = await thread_handler.get_active_thread(recipient)

    is_in_shift: bool = (
        client_ordelo.table("rider_master")
        .select("is_in_shift")
        .eq("rider_id", recipient)
        .execute()
        .data[0]["is_in_shift"]
    )

    # If not on active delivery and is not in shift
    if not is_in_shift:
        await enquire_shift_availability_non_template(wa, msg)
        return
    # If not on active delivery and is in shift
    elif thread_row is None and is_in_shift:
        intent_response = get_rider_intent(msg.text)
        if intent_response.intent == "End Shift":
            await enquire_shift_availability_non_template(wa, msg)
        else:
            await wa.send_message(to=recipient, text="You have no active delivery")
        return

    # Run the graph
    _state_update_dict = {"latest_wa_msg_id": msg.id}
    await run_rider_agent_w_custom_msg(
        recipient, human_msg=msg.text, state_update_dict=_state_update_dict
    )


async def init_delivery_summary(order_number: str, recipient: str):
    """Background task to initialize delivery via RPC call."""
    try:
        # Run the blocking RPC call in a thread pool to avoid blocking the event loop
        response = await asyncio.to_thread(
            lambda: client_ordelo.rpc(
                "init_delivery",
                {"p_cust_id": recipient, "p_order_number": order_number},
            ).execute()
        )
        logger.info(
            f"init_delivery completed for order {order_number} with response {response}"
        )
    except Exception as e:
        logger.error(f"init_delivery failed for order {order_number}: {e}")


# %% Test Delivery
TEST_DELIVERY = filters.contains("/test", ignore_case=True)


async def test_delivery(wa: WhatsApp, msg: Message):
    # pool: AsyncConnectionPool = await pg_settings.get_pool()
    # client = pg_settings.client
    logger.info(
        "Testing delivery for user %s with order %s", msg.sender, "WREN-AEHO-21"
    )
    recipient = msg.sender
    order_number = "WREN-AEHO-21"

    # order_number = f"WREN-TEST-{random.randint(10, 99)}"

    # DB operations
    # Cleanup - update dispatch complete
    client_ordelo.rpc(
        "cleanup_delivery_order", {"p_order_number": order_number}
    ).execute()

    # Now init the delivery so the process follows - run as background task to avoid timeout
    logger.info(f"Initializing delivery for user {recipient} with order {order_number}")

    # Create an entry in delivery_summary and update status to unassigned (bypass the restaurant confirmation)
    asyncio.create_task(init_delivery_summary(order_number, recipient))
    client_ordelo.table("delivery_summary").update({"status": "unassigned"}).eq(
        "order_number", order_number
    ).execute()

    logger.info(f"Init delivery scheduled as background task for order {order_number}")
    return {"status": "success"}

    # open_dispatch = (
    #     client.table("delivery_dispatch")
    #     .select("dispatch_id")
    #     .eq("status", "assigned")
    #     .execute()
    # )
    # for dispatch in open_dispatch.data:
    #     client.rpc(
    #         "dispatch_complete_func", {"p_dispatch_id": dispatch["dispatch_id"]}
    #     ).execute()

    # await sbase_call_function(
    #     function_name="dispatch_complete_func",
    #     input_args={"p_dispatch_id": dispatch["dispatch_id"]},
    # )

    # Cleanup - delete from rider_location_event
    delete_old_location_events = (
        f"DELETE FROM rider_location_event WHERE order_number = '{order_number}'"
    )
    await execute_sql_query(query=delete_old_location_events)
    # Cleanup complete;

    # # Move to inserting the order; Create reference in pricing_detail table
    # client.table("delivery_pricing_detail").insert(
    #     {"order_number": order_number, "distance": 0.83}
    # ).execute()

    # Update a different order to instead on inserting into delivery_option
    # example_order_to_update = (
    #     client.table("delivery_option")
    #     .select("order_number")
    #     .like("order_number", "WREN-TEST-%")
    #     .order("id", desc=True)
    #     .limit(1)
    #     .execute()
    #     .data[0]["order_number"]
    # )

    # client.table("delivery_option").update({"order_number": order_number}).eq(
    #     "order_number", example_order_to_update
    # ).execute()

    # Now init the delivery so the process follows
    logger.info(f"Initializing delivery for user {recipient} with order {order_number}")
    client_ordelo.rpc(
        "init_delivery", {"p_cust_id": recipient, "p_order_number": order_number}
    ).execute()


# %% Clear Dispatch
CLEAR_DISPATCH = filters.contains("/cleardis", ignore_case=True)


async def clear_dispatch(wa: WhatsApp, msg: Message):
    recipient = msg.from_user.wa_id
    client = pg_settings.client
    client.rpc("clear_dispatch", {}).execute()


# %% Live map location
LIVE_LOCATION = filters.contains("/live", ignore_case=True)


async def send_live_map_location(wa: WhatsApp, msg: Message):
    recipient = msg.sender
    # Change mode
    # _inflight = await sbase_get(table_name="delivery_inflight", rider_id=recipient)
    _inflight = (
        client_ordelo.table("delivery_inflight")
        .select("*")
        .eq("rider_id", recipient)
        .execute()
        .data
    )

    if len(_inflight) == 0:
        await wa.send_message(
            to=recipient, text="Location not available. You have no active delivery"
        )
        return

    order_number = _inflight[0]["order_number"]
    rest_ref = order_number.split("-")[0]
    restaurant_base_url = await get_restaurant_base_url_async(rest_ref)
    live_map_url = await get_live_map_location_url(order_number)
    if live_map_url is None:
        await wa.send_message(to=recipient, text="Live map location not available")
        return
    url = f"{restaurant_base_url}/location-hooks/live-location-map/{order_number}"
    await wa.send_message(to=recipient, text=url)


# %% Test flow
TEST_FLOW = filters.contains("/flow", ignore_case=True)


async def test_flow(wa: WhatsApp, msg: Message):
    recipient = msg.sender
    _sync_wa_client.send_message(
        to=recipient,
        text="Update your address details",
        buttons=FlowButton(
            title="Update Details",
            flow_id=955259853427256,  # The `static_flow` flow id from above
            flow_token="123",
            # mode=FlowStatus.DRAFT,
            flow_action_type=FlowActionType.NAVIGATE,
            flow_action_screen="START",  # The screen id to open when the user clicks the button
            flow_action_payload={
                "flow_name": "Postcode Search",
                "customer_id": "44744123123123",
                "postcode_init": "BR6 6DN",
            },
        ),
    )


# %% Reset
WHEN_RESET = filters.contains("/reset", ignore_case=True)


async def reset_thread(wa: WhatsApp, msg: Message):
    pool: AsyncConnectionPool = await pg_settings.get_pool()
    thread_handler = ThreadHandler(pool)
    logger.info("=============== reset the thread ===============")
    recipient = msg.from_user.wa_id

    # _inflight = await sbase_get("delivery_inflight", rider_id=recipient)
    _inflight = (
        client_ordelo.table("delivery_inflight")
        .select("*")
        .eq("rider_id", recipient)
        .execute()
        .data
    )

    # Exit if there is no active dispatch
    if len(_inflight) != 0:
        dispatch_id = _inflight[0]["dispatch_id"]
        # await sbase_call_function(
        #     function_name="dispatch_complete_func",
        #     input_args={"p_dispatch_id": dispatch_id},
        # )
        client_ordelo.rpc(
            "dispatch_complete_func", {"p_dispatch_id": dispatch_id}
        ).execute()

    await thread_handler.make_threads_inactive(recipient=recipient)
    await wa.send_message(to=recipient, text="Starting new conversation")


# %% live_location
async def live_location(wa: WhatsApp, msg: Message):
    # toDo - change to pool from pg_settings.
    pool: AsyncConnectionPool = await pg_settings.get_pool()
    recipient = msg.sender
    logger.info("liv_location requested ...")

    # _inflight = await sbase_get(table_name="delivery_inflight", rider_id=recipient)
    _inflight = (
        client_ordelo.table("delivery_inflight")
        .select("*")
        .eq("rider_id", recipient)
        .execute()
        .data
    )

    if len(_inflight) == 0:
        await wa.send_message(
            to=recipient, text="Location not available. You have no active delivery"
        )
        return

    order_number = _inflight[0]["order_number"]
    # live location logic, reused
    query = """
    SELECT 
        lat, 
        lon
    FROM rider_location LOC INNER JOIN delivery_inflight DI
    ON LOC.rider_id = DI.rider_id
    WHERE LOC.order_number = %s
    ORDER BY tst DESC
    LIMIT 1
    """
    result = await execute_sql_query(pool, query, (order_number,))
    if result is None:
        return None

    lat, lon = result[0]

    logger.info(f"lat:{lat}, lon:{lon}")

    live_map_url = f"https://maps.google.com/?q=Order('{order_number}')@{lat},{lon}"
    logger.info(live_map_url)
    await wa.send_message(to=recipient, text=live_map_url)


# %% Only references
def handle_callback_button(wa: WhatsApp, clb: types.CallbackButton):
    print(clb.data)


def on_sign_up_request(_: WhatsApp, request: FlowRequest) -> FlowResponse | None:
    logger.info(request)
    logger.info(request.data)

    if request.has_error:
        logger.error("Flow request has error: %s", request.data)
        return FlowResponse(data={"acknowledged": True})

    return FlowResponse(
        version=request.version,
        screen="START",
        data={
            "customer_name": "John Doe",
            "customer_id": "44744123123123",
            "address": "one kingdom street",
        },
    )
