"""
WhatsApp message handler for Ordelo delivery system
    . Processes incoming WhatsApp messages from riders and customers
    . Handles command parsing and execution for delivery operations
    . Manages live location sharing and tracking
    . Provides delivery status updates and notifications
    . Integrates with OrdeloAgent for delivery workflow orchestration
    . Supports command-based interactions for delivery management
    . Handles error cases and provides appropriate responses
  Functions/Classes:
    . process_wa_msg - Main entry point for WhatsApp message processing
    . live_location - Handles live location updates from riders
    . reset_thread - Resets conversation thread state
    . test_delivery - Creates test delivery for debugging
    . handle_rider_command - Processes commands from delivery riders
    . clear_dispatch - Clears active dispatch assignments
    . send_live_map_location - Shares live location map with rider
    . handle_callback_button - Handles rider responses to dispatches
"""

# %%
from pywa_async import WhatsApp, types
from config import logger, _sync_wa_client, pg_settings
from pywa.types.flows import FlowRequest, FlowResponse
from pywa.types import Message
import random

# project modules
from utils_common.db_utils.sbase_rest_ops import sbase_get, sbase_call_function
from utils_common.db_utils.sbase_pool_ops import execute_sql_query
from pywa.types.flows import FlowActionType
from pywa.types import FlowButton
from utils_common.thread_management import ThreadHandler
from psycopg_pool import AsyncConnectionPool
from ordelo.agents.agent_runner import run_rider_graph, run_byteloop_agent
from ordelo.agent_app_handlers import get_live_map_location_url


# %% Run graph on msg
async def process_wa_msg(wa: WhatsApp, msg: Message):
    await msg.indicate_typing()
    pool: AsyncConnectionPool = await pg_settings.get_pool()
    recipient = msg.sender
    thread_handler = ThreadHandler(pool)

    thread_row = await thread_handler.get_active_thread(recipient)

    # exit if there is not active delivery
    if thread_row is None:
        await wa.send_message(to=recipient, text="You have no active delivery")
        return

    # Run the graph
    await run_rider_graph(recipient, human_msg=msg.text)


# %% Run byteloop agent on msg
async def process_byteloop_agent(wa: WhatsApp, msg: Message):
    await msg.indicate_typing()
    recipient = msg.sender
    user_name = msg.from_user.name
    # Run the graph
    messages = await run_byteloop_agent(
        recipient, user_name=user_name, human_msg=msg.text
    )
    await wa.send_message(to=recipient, text=messages)


# %% Reset
async def reset_thread(wa: WhatsApp, msg: Message):
    pool: AsyncConnectionPool = await pg_settings.get_pool()
    thread_handler = ThreadHandler(pool)
    logger.info("=============== reset the thread ===============")
    recipient = msg.from_user.wa_id

    _inflight = await sbase_get("delivery_inflight", rider_id=recipient)

    # Exit if there is no active dispatch
    if len(_inflight) != 0:
        dispatch_id = _inflight[0]["dispatch_id"]
        await sbase_call_function(
            function_name="dispatch_complete_func",
            input_args={"p_dispatch_id": dispatch_id},
        )

    await thread_handler.make_threads_inactive(from_number=recipient)
    await wa.send_message(to=recipient, text="Starting new conversation")


# %% Clear Dispatch
async def clear_dispatch(wa: WhatsApp, msg: Message):
    recipient = msg.from_user.wa_id
    client = pg_settings.client
    client.rpc("clear_dispatch", {}).execute()


# %% Test Delivery
async def test_delivery(wa: WhatsApp, msg: Message):
    pool: AsyncConnectionPool = await pg_settings.get_pool()
    client = pg_settings.client
    recipient = msg.sender
    order_number = f"WREN-TEST-{random.randint(10, 99)}"

    # DB operations
    # Cleanup - update dispatch complete
    open_dispatch = (
        client.table("delivery_dispatch")
        .select("dispatch_id")
        .eq("status", "assigned")
        .execute()
    )
    for dispatch in open_dispatch.data:
        await sbase_call_function(
            function_name="dispatch_complete_func",
            input_args={"p_dispatch_id": dispatch["dispatch_id"]},
        )

    # Cleanup - delete from rider_location_event
    delete_old_location_events = (
        f"DELETE FROM rider_location_event WHERE order_number = '{order_number}'"
    )
    await execute_sql_query(query=delete_old_location_events)
    # Cleanup complete;

    # Move to inserting the order; Create reference in pricing_detail table
    client.table("delivery_pricing_detail").insert(
        {"order_number": order_number, "distance": 0.83}
    ).execute()

    # Update a different order to instead on inserting into delivery_option
    example_order_to_update = (
        client.table("delivery_option")
        .select("order_number")
        .like("order_number", "WREN-TEST-%")
        .order("id", desc=True)
        .limit(1)
        .execute()
        .data[0]["order_number"]
    )

    client.table("delivery_option").update({"order_number": order_number}).eq(
        "order_number", example_order_to_update
    ).execute()

    # Now init the delivery so the process follows
    client.rpc(
        "init_delivery", {"p_cust_id": recipient, "p_order_number": order_number}
    ).execute()


# %%
async def send_live_map_location(wa: WhatsApp, msg: Message):
    recipient = msg.sender
    _inflight = await sbase_get(table_name="delivery_inflight", rider_id=recipient)

    if len(_inflight) == 0:
        await wa.send_message(
            to=recipient, text="Location not available. You have no active delivery"
        )
        return

    order_number = _inflight[0]["order_number"]
    live_map_url = await get_live_map_location_url(order_number)
    if live_map_url is None:
        await wa.send_message(to=recipient, text="Live map location not available")
        return
    url = f"https://agent.ordelo.app/location-hooks/live-location-map/{order_number}"
    await wa.send_message(to=recipient, text=url)


# %% Test flow
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


# %% live_location
async def live_location(wa: WhatsApp, msg: Message):
    # toDo - change to pool from pg_settings.
    pool: AsyncConnectionPool = await pg_settings.get_pool()
    recipient = msg.sender
    logger.info("liv_location requested ...")

    _inflight = await sbase_get(table_name="delivery_inflight", rider_id=recipient)

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
