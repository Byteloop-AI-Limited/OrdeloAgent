"""
Agent app handlers for Ordelo delivery agent workflows and WhatsApp integration.
    . Manages rider dispatch responses and delivery state transitions via WhatsApp
    . Generates agent configuration links and job control (start/stop) configs
    . Handles synchronous rider response processing with database updates
    . Provides live map location URLs and tracking enablement checks
    . Posts webhook events for customer and restaurant confirmation codes
    . Sends delivery instructions via WhatsApp with pickup/drop-off details
    . Includes debugging utilities for state inspection and thread analysis
    . Integrates with PostgreSQL for delivery detail and dispatch management
    . Supports both template-based and non-template WhatsApp message sending for shift availability
  Functions/Classes:
    . process_dispatch_response_from_rider_sync - Handle rider accept/decline responses
    . generate_config_href - Create configuration URLs for agent setup
    . create_start_job_config - Generate job start configuration for agents
    . create_stop_job_config - Generate job stop configuration for agents
    . initial_handle_of_rider_response - Async processing of rider responses
    . get_live_map_location_url - Generate live tracking URLs for orders
    . is_live_location_enabled - Check if live location is active for order
    . CallbackButtonData - Pydantic model for WhatsApp callback button data
    . enquire_shift_availability_non_template - Send shift availability inquiry using regular messages
    . enquire_shift_availability - Send shift availability inquiry using WhatsApp templates
    . _send_delivery_instructions - Send pickup/drop-off instructions via WhatsApp
    . post_rider_event_customer_cc - Post customer confirmation code events
    . post_rider_event_restaurant_cc - Post restaurant confirmation code events
    . debug_state - Debug utility for inspecting agent state
    . debug_state_by_thread - Debug utility for thread-specific state inspection
"""

# %%
import base64
import json
from datetime import datetime
import psycopg
from psycopg_pool import ConnectionPool
from ordelo_datamodels.delivery_pymodels import DeliveryDetail
from pywa_async import WhatsApp
from datetime import timedelta
from pywa.types import Message, Template as Temp, ButtonUrl, Button
from config import (
    pg_settings,
    _async_wa_client,
    logger,
    _sync_wa_client,
    project_settings,
    get_webhook_url,
    client_ordelo,
)
from pydantic import BaseModel
from typing import Optional
import httpx
from utils_common.lg_utils import (
    get_state_values,
    shorten_state_messages,
    get_config_for_recipient,
)
import pytz
from utils_common.db_utils.sbase_pool_ops import execute_sql_query

client = pg_settings.client


# %% Supporting Funcs
def process_dispatch_response_from_rider_sync(
    pool_sync: ConnectionPool,
    rider_id: str,
    callback_data: dict,
    _sync_wa_client: WhatsApp = _sync_wa_client,
):
    """
    Processes the rider's response to a delivery dispatch in a synchronous context.

    Depending on whether the rider accepted or declined the job, it updates the
    delivery dispatch and delivery detail records in the database accordingly.

    Args:
        pool_sync (ConnectionPool): A synchronous connection pool for database operations.
        recipient (str): The phone number of the rider.
        callback_data (dict): The callback data containing the dispatch ID, order number, and rider response.
        _sync_wa_client (WhatsApp, optional): The WhatsApp client for sending messages. Defaults to _sync_wa_client.

    """
    dispatch_id = callback_data["dispatch_id"]
    order_number = callback_data["order_number"]
    rider_response = callback_data["status"]
    return_value = ""

    with pool_sync.connection() as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            if rider_response == "accepted":
                # Check current status
                cur.execute(
                    "SELECT * FROM delivery_detail WHERE order_number = %s",
                    (order_number,),
                )
                _detail = cur.fetchone()

                if _detail and _detail["status"] == "assigned":
                    # Job already assigned, update dtts
                    cur.execute(
                        """
                        UPDATE delivery_dispatch 
                        SET status_update_dtts = %s 
                        WHERE dispatch_id = %s
                        """,
                        (datetime.now().isoformat(), dispatch_id),
                    )
                    # Job already assigned
                    _sync_wa_client.send_message(
                        to=rider_id, text="Sorry, This job has already been assigned"
                    )
                    return_value = "job already assigned"
                else:
                    # dispatch_accepted; Needs to send back the delivery detail
                    cur.execute(
                        """
                        SELECT dispatch_accept_func(%s, %s, %s)
                        """,
                        (dispatch_id, order_number, rider_id),
                    )
                    _detail = cur.fetchone()
                    if not isinstance(_detail["dispatch_accept_func"], dict):
                        logger.error("Issue with return type of dispatch_accept_func")
                        _sync_wa_client.send_message(
                            to=rider_id, text="Thank you for accepting the job!"
                        )
                    return_value = _detail["dispatch_accept_func"]

            elif rider_response == "declined":
                cur.execute(
                    """
                    UPDATE delivery_dispatch 
                    SET status = 'declined', status_update_dtts = %s 
                    WHERE dispatch_id = %s
                    """,
                    (datetime.now().isoformat(), dispatch_id),
                )
                return_value = "job declined"
        conn.commit()
        return return_value


# %% Generate Config Href
def generate_config_href(config: dict) -> str:
    config_json = json.dumps(config)
    config_base64 = base64.b64encode(config_json.encode()).decode()
    return f"owntracks:///config?inline={config_base64}"


# %% Start Job Config
async def create_start_job_config(d_detail: DeliveryDetail) -> str:
    waypoints = [
        {
            "_type": "waypoint",
            "tst": int(datetime.now().timestamp()),
            "rid": "rest",
            "desc": "rest",
            "rad": 200,
            "lat": d_detail.rest_lat,
            "lon": d_detail.rest_lon,
        },
        {
            "_type": "waypoint",
            "tst": int(datetime.now().timestamp()),
            "rid": "cust",
            "desc": "cust",
            "rad": 200,
            "lat": d_detail.customer_lat,
            "lon": d_detail.customer_lon,
        },
    ]

    start_job_config = {
        "_type": "configuration",
        "mode": 3,
        "allowRemoteLocation": True,
        "usePassword": False,
        # "url": f"{project_settings.base_url}/location-hooks/pub",
        "url": "https://pqsvhidiwiydgshynfib.supabase.co/functions/v1/owntracks-webhook",
        "monitoring": 2,
        "locatorDisplacement": 10,
        "locatorInterval": 30,
        "username": d_detail.rider_id,
        "deviceId": f"{d_detail.rider_id}-{d_detail.order_number}",
        "password": "",
        "waypoints": waypoints,
    }

    # Encode config as href
    start_href = generate_config_href(start_job_config)

    return start_href


# %% Stop Job Config
stop_job_config = {
    "_type": "configuration",
    "mode": 3,
    "allowRemoteLocation": False,
    # "usePassword": False,
    # "username": "NA",
    "device_id": "NA",
    # "password": "",
    "monitoring": -1,
    "url": "",
}


async def create_stop_job_config() -> str:
    # Encode config as href
    stop_href = generate_config_href(stop_job_config)
    return stop_href


# %%
async def initial_handle_of_rider_response(
    order_status: dict,
    callback_data: dict,
    _async_wa_client: WhatsApp = _async_wa_client,
):
    logger.info(f"Initial handle of rider response: {callback_data}")
    logger.info(f"Order status: {order_status}")

    # handle declined so the rest does not have tobe in an else block
    if callback_data["status"] == "declined":
        client.table("delivery_dispatch").update({"status": "declined"}).eq(
            "dispatch_id", callback_data["dispatch_id"]
        ).execute()
        return

    # now handle the accept, eagerly handle unassigned
    if order_status["status"] == "unassigned":
        # Update dispatch status, will be done for all accepted dispatches
        client.table("delivery_dispatch").update({"status": "accepted"}).eq(
            "dispatch_id", callback_data["dispatch_id"]
        ).execute()
        return
    elif order_status["status"] == "completed":
        logger.info(
            "Delivery job already completed for order number: {}".format(
                callback_data["order_number"]
            )
        )
        await _async_wa_client.send_message(
            to=callback_data["rider_id"], text="Sorry, This job is no longer available"
        )
        return
    elif order_status["status"] == "timedout":
        logger.info(
            "Delivery job already timed out for order number: {}".format(
                callback_data["order_number"]
            )
        )
        await _async_wa_client.send_message(
            to=callback_data["rider_id"], text="Sorry, This job is no longer available"
        )
        return


# %% Live map location
async def get_live_map_location_url(order_number: str):
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
    result = await execute_sql_query(query, (order_number,))
    if len(result) == 0:
        return None

    lat, lon = result[0]

    logger.info(f"lat:{lat}, lon:{lon}")

    live_map_url = f"https://maps.google.com/?q=Order('{order_number}')@{lat},{lon}"

    return live_map_url


# %%
def is_live_location_enabled(order_number):
    rows = (
        pg_settings.client.table("rider_location")
        .select("*")
        .like("order_number", order_number)
        .limit(10)
        .execute()
        .data
    )
    return len(rows) > 0


# %% Callback model
class CallbackButtonData(BaseModel):
    model_config = {"frozen": True}
    action: str
    recipient: str
    ai_msg: str
    human_msg: str
    response: Optional[str] = None


# %% Enquire shift availability (non-template version)
async def enquire_shift_availability_non_template(wa: WhatsApp, msg: Message):
    recipient = msg.sender
    shift_available_cb_data = CallbackButtonData(
        action="/shiftAvailability",
        recipient=recipient,
        ai_msg="",
        human_msg="Yes",
    )
    shift_not_available_cb_data = CallbackButtonData(
        action="/shiftAvailability",
        recipient=recipient,
        ai_msg="",
        human_msg="No",
    )
    msg_id = await _async_wa_client.send_message(
        to=recipient,
        header="🌟 Shift Availability 🌟",
        text="Are you available for deliveries today?",
        reply_to_message_id=None,
        buttons=[
            Button(
                title="Yes", callback_data=shift_available_cb_data.model_dump_json()
            ),
            Button(
                title="No",
                callback_data=shift_not_available_cb_data.model_dump_json(),
            ),
        ],
    )
    return msg_id


# %% Enquire shift availability (template version)
async def enquire_shift_availability(wa: WhatsApp, recipient: str, name: str):
    shift_available_cb_data = CallbackButtonData(
        action="/shiftAvailability",
        recipient=recipient,
        ai_msg="",
        human_msg="Yes",
    )
    shift_not_available_cb_data = CallbackButtonData(
        action="/shiftAvailability",
        recipient=recipient,
        ai_msg="",
        human_msg="No",
    )
    msg_id = await wa.send_template(
        to=recipient,
        template=Temp(
            name="shift_availability",
            language=Temp.Language.ENGLISH_UK,
            body=[
                Temp.TextValue(value=name),
            ],
            buttons=[
                Temp.QuickReplyButtonData(data=shift_available_cb_data.model_dump_json()),
                Temp.QuickReplyButtonData(data=shift_not_available_cb_data.model_dump_json()),
            ],
        ),
    )
    return msg_id


# %%


# %%


async def _send_delivery_instructions(
    dispatch_id: int, start_live_tracking_url: str, recipient: str, rider_name: str
):
    """
    Sends delivery instructions (pickup and drop-off locations) via WhatsApp for a given dispatch_id.
    """
    client = pg_settings.client
    pickup_cb_data = CallbackButtonData(
        action="/riderLocationRequest",
        recipient=recipient,
        ai_msg="",
        human_msg="Send me the pickup location",
        response="",
    )
    dropoff_cb_data = CallbackButtonData(
        action="/riderLocationRequest",
        recipient=recipient,
        ai_msg="",
        human_msg="Send me the dropoff location",
        response="",
    )

    dispatch = (
        client.table("delivery_dispatch")
        .select("*")
        .eq("dispatch_id", dispatch_id)
        .limit(1)
        .execute()
        .data[0]
    )
    order_number = dispatch["order_number"]

    summary = (
        client.table("delivery_summary")
        .select("*")
        .eq("order_number", order_number)
        .limit(1)
        .execute()
        .data[0]
    )

    delivery_summary_dtts = datetime.fromisoformat(summary["dtts"])

    uk_tz = pytz.timezone("Europe/London")
    # convert dtts to UK local time (handles BST/GMT automatically)
    delivery_summary_dtts = delivery_summary_dtts.astimezone(uk_tz)
    pickup_time = (delivery_summary_dtts + timedelta(minutes=25)).strftime("%I:%M %p")

    body_text = f"""
Hi {rider_name}, here are the Delivery details:
  ⏰ Pickup Time - *@{pickup_time}*
  💰 Earning - *£{dispatch["rider_payout"]}*
  🛣️ Distance - *{dispatch["distance"]} miles*

🔑 After pickup, send me the 2-digit *Restaurant* confirmation code

🔑 After dropoff, send me the 2-digit *Customer* confirmation code

👨‍💻 Please let me know if you have any questions during the delivery process.
    """
    reply_to_msg_id = await _async_wa_client.send_message(
        to=recipient,
        header=f"🌟 {summary['order_number']} 🌟",
        text=body_text,
        reply_to_message_id=None,
        buttons=[
            Button(
                title="Pickup Location", callback_data=pickup_cb_data.model_dump_json()
            ),
            Button(
                title="Dropoff Location",
                callback_data=dropoff_cb_data.model_dump_json(),
            ),
        ],
    )

    # Send the URL to the rider
    # await _async_wa_client.send_message(
    #     to=recipient,
    #     header="Enable Live Tracking",
    #     text="Please turn on the live tracking by clicking the link below.",
    #     reply_to_message_id=reply_to_msg_id.id,
    #     buttons=ButtonUrl(title="Start live tracking", url=start_live_tracking_url),
    # )
    return reply_to_msg_id.id, body_text


# %% Test
# dispatch_id = 2864
# await _send_delivery_instructions(dispatch_id, "https://agent.ordelo.co.uk", "447448440754")


# %%
async def post_rider_event_customer_cc(order_number: str, customer_id: int):
    """
    Posts a customer confirmation code event for a given order_number to the appropriate webhook.

    Args:
        order_number (str): The unique identifier for the order.

    Side Effects:
        Sends an HTTP POST request to the configured rider-customer-cc webhook endpoint
        and prints the response status and JSON.
    """
    rest_ref = order_number.split("-")[0]
    async with httpx.AsyncClient() as client:
        await client.post(
            get_webhook_url(rest_ref, "rider-cust-cc")
            + "/"
            + order_number
            + "/"
            + str(customer_id),
            json={},
        )
        logger.info("Cust-CC Webhook called for order number: {}".format(order_number))


# %%
async def post_rider_event_restaurant_cc(order_number: str, customer_id: int):
    """
    Posts a restaurant confirmation code event for a given order_number to the appropriate webhook.

    Args:
        order_number (str): The unique identifier for the order.
        customer_id (int): The unique identifier for the customer.

    Side Effects:
        Sends an HTTP POST request to the configured rider-restaurant-cc webhook endpoint
        and logs the call.
    """
    rest_ref = order_number.split("-")[0]
    async with httpx.AsyncClient() as client:
        await client.post(
            get_webhook_url(rest_ref, "rider-rest-cc")
            + "/"
            + order_number
            + "/"
            + str(customer_id),
            json={},
        )
        logger.info("Rest-CC Webhook called for order number: {}".format(order_number))


# %% Debug State
async def debug_state(recipient: str, graph, pool) -> dict:
    config = await get_config_for_recipient(recipient, pool)
    state = await graph.aget_state(config=config)

    debug_stack = {
        **get_state_values(state.values),
        "messages": shorten_state_messages(state.values["messages"]),
    }
    return debug_stack


# %% Debug State by thread_id
async def debug_state_by_thread(recipient: str, thread_id: str, graph, pool) -> dict:
    config = {"configurable": {"thread_id": thread_id, "recipient": recipient}}
    state = await graph.aget_state(config=config)

    debug_stack = {
        **get_state_values(state.values),
        "messages": shorten_state_messages(state.values["messages"]),
    }
    return debug_stack
