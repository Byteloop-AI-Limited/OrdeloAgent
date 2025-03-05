"""
All handlers for the fastapi app that serves the Elai Ai agent
"""
# %%
import base64
import json
from datetime import datetime
import asyncio

from langchain_core.messages import HumanMessage, SystemMessage
from pywa_async.types import Message
import psycopg
from config import logger, _async_wa_client, project_settings, _sync_wa_client
from ordelo_datamodels.delivery_pymodels import DeliveryDetail
from utils_common.lg_utils import get_state_values, shorten_state_messages, get_config_for_recipient
from psycopg_pool import ConnectionPool
from pywa.types import ButtonUrl
from pywa_async import WhatsApp


# %% Supporting Funcs
def process_dispatch_response_from_rider_sync(
    pool_sync: ConnectionPool,
    rider_id: str,
    callback_data: dict,
    _sync_wa_client: WhatsApp = _sync_wa_client
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
    dispatch_id = callback_data['dispatch_id']
    order_number = callback_data['order_number']
    rider_response = callback_data['status']
    return_value = ''

    with pool_sync.connection() as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            if rider_response == 'accepted':
                # Check current status
                cur.execute(
                    "SELECT * FROM delivery_detail WHERE order_number = %s",
                    (order_number,)
                )
                _detail = cur.fetchone()

                if _detail and _detail['status'] == 'assigned':
                    # Job already assigned, update dtts
                    cur.execute(
                        """
                        UPDATE delivery_dispatch 
                        SET status_update_dtts = %s 
                        WHERE dispatch_id = %s
                        """,
                        (datetime.now().isoformat(), dispatch_id)
                    )
                    # Job already assigned
                    _sync_wa_client.send_message(
                        to=rider_id,
                        text='Sorry, This job has already been assigned'
                    )
                    return_value = "job already assigned"
                else:
                    # dispatch_accepted; Needs to send back the delivery detail
                    cur.execute(
                        """
                        SELECT dispatch_accept_func(%s, %s, %s)
                        """,
                            (dispatch_id, order_number, rider_id)
                        )
                    _detail = cur.fetchone()
                    if not isinstance(_detail['dispatch_accept_func'], dict):
                        logger.error("Issue with return type of dispatch_accept_func")
                        _sync_wa_client.send_message(
                            to=rider_id,
                            text='Thank you for accepting the job!'
                        )
                    return_value = _detail['dispatch_accept_func']

            elif rider_response == 'declined':
                cur.execute(
                    """
                    UPDATE delivery_dispatch 
                    SET status = 'declined', status_update_dtts = %s 
                    WHERE dispatch_id = %s
                    """,
                    (datetime.now().isoformat(), dispatch_id)
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
async def create_start_job_config(
    d_detail: DeliveryDetail
    ) -> str:
    waypoints = [
        {
            "_type": "waypoint",
            "tst": int(datetime.now().timestamp()),
            "rid": "rest",
            "desc": "rest",
            "rad": 10,
            "lat": d_detail.rest_lat,
            "lon": d_detail.rest_lon
        },
        {
            "_type": "waypoint",
            "tst": int(datetime.now().timestamp()),
            "rid": "cust",
            "desc": "cust",
            "rad": 10,
            "lat": d_detail.customer_lat,
            "lon": d_detail.customer_lon
        },
        ]

    start_job_config = {
        "_type": "configuration",
        "mode": 3,
        "allowRemoteLocation": True,
        "usePassword" : False,
        "monitoring": 2,
        "username": d_detail.rider_id,
        "deviceId": f"{d_detail.rider_id}-{d_detail.order_number}",
        "password": "",
        "url": f"{project_settings.base_url}/location-hooks/pub",
        "locatorDisplacement": 10,
        "locatorInterval" : 60,
        "waypoints": waypoints
    }

    # Encode config as href
    start_href = generate_config_href(start_job_config)

    return start_href

# %% Stop Job Config
stop_job_config = {
        "_type": "configuration",
        "mode": 3,
        "allowRemoteLocation": False,
        "usePassword" : False,
        "monitoring": -1,
        "username": "NA",
        "password": "",
        "url": "",
    }
async def create_stop_job_config() -> str:
    # Encode config as href
    stop_href = generate_config_href(stop_job_config)
    return stop_href

# %% Initialize Ordelo Graph

async def init_ordelo_graph(
    graph, 
    pool, 
    d_detail: DeliveryDetail
    ):
    logger.info(f"Initializing Ordelo Graph with rider_id {d_detail.rider_id}")
    # Setup Graph
    start_live_tracking_url = await create_start_job_config(
        d_detail
        )
    
    config = await get_config_for_recipient(d_detail.rider_id, pool)

    # update graph state
        # Setup context 
    ip_msgs = {
        "messages": [
            SystemMessage("Rider has accepted the delivery job, send the live tracking link."),
            HumanMessage("I have accepted the delivery job."),
        ]
    }
    delivery_start_dtts = datetime.now().isoformat()
    await graph.aupdate_state(  
        config,
        {
            "dispatch_id": d_detail.dispatch_id,
            "order_number": d_detail.order_number,
            "start_live_tracking_url": start_live_tracking_url,
            "delivery_start_dtts": delivery_start_dtts
        },
        as_node="toolNode",
    )
    # Run Graph
    await graph.ainvoke(input=ip_msgs, config=config)
    
    # Verify if live location enabled
        # sleep for 4 seconds
    await asyncio.sleep(65)
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT * FROM
                rider_location riderLocation
                WHERE rider_id=%s AND order_number=%s AND dtts >= %s AND EXISTS
                (SELECT 1 from delivery_inflight 
                WHERE rider_id = riderLocation.rider_id
                AND order_number = riderLocation.order_number
                )
                """,
                (d_detail.rider_id, d_detail.order_number, delivery_start_dtts)
            )
            location_data = await cur.fetchone()

    if location_data:
        logger.success(f"location data being recieved from {d_detail.rider_id}: {location_data}")
    else:
        text="I am unable to get your live location, please enable it by clicking the link sent to you."
        await _async_wa_client.send_message(
            to=d_detail.rider_id,
            header=d_detail.order_number,
            text=text,
            reply_to_message_id=None,
            buttons=ButtonUrl(title="Start live tracking", url=start_live_tracking_url)
        )

# %% Run Ordelo Graph
async def run_ordelo_graph(msg: Message, graph, pool):
    """Executes the takeaway graph and returns the AI's response."""
    human_msg = msg.text
    recipient = msg.sender
    wa_user_name = msg.from_user.name

    config = await get_config_for_recipient(recipient, pool)

    # Check is name is captured
    state = await graph.aget_state(config=config)
    if not state.values.get(" "):
        _system_msg = f"""User Name {wa_user_name}. Address by name 
        in scenarios like first messages, When there is change in intent, user frustrated. Dont over do it.
        """
        await graph.aupdate_state(
            config,
            {"wa_user_name": wa_user_name, "messages": [SystemMessage(_system_msg)]},
            as_node="toolNode",
        )

    ip_msgs = {
        "messages": [
            HumanMessage(human_msg),
        ]
    }

    ai_msg = await graph.ainvoke(input=ip_msgs, config=config)
    # Debug
    recent_msgs = ai_msg["messages"][-4:]
    [logger.info(msg.content) for msg in recent_msgs]

    ai_msg_content = ai_msg["messages"][-1].content

    return ai_msg_content

# %% Debug state
# %% Debug State
async def debug_state(recipient: str, graph, pool) -> dict:
    config = await get_config_for_recipient(recipient, pool)
    state = await graph.aget_state(config=config)

    debug_stack = {
        **get_state_values(state.values),
        "messages": shorten_state_messages(state.values["messages"]),
    }
    return debug_stack
