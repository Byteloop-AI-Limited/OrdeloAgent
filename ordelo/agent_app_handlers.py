"""
All handlers for the fastapi app that serves the Elai Ai agent
"""
# %%
import base64
import json
from datetime import datetime
import asyncio

import uvicorn
from langchain_core.messages import HumanMessage, SystemMessage
from pywa_async.types import Message
from psycopg_pool import AsyncConnectionPool
import psycopg
from config import logger, _async_wa_client
from ordelo_datamodels.delivery_pymodels import DeliveryDetail, DeliveryDispatch
from utils_common.db_utils.sbase_rest_ops import sbase_get
from utils_common.db_utils.sbase_pool_ops import execute_sql_query
from utils_common.lg_utils import get_config_for_recipient

# %% Funcs
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
        "url": "https://live-track.byteloop.ai/location-hooks/pub",
        "locatorDisplacement": 10,
        "locatorInterval" : 60,
        "waypoints": waypoints
    }

    # Encode config as href
    start_href = generate_config_href(start_job_config)

    return start_href

# %% 
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
                rider_location 
                WHERE rider_id=%s AND order_number=%s AND dtts >= %s
                """,
                (d_detail.rider_id, d_detail.order_number, delivery_start_dtts)
            )
            location_data = await cur.fetchone()
    
    if location_data:
        logger.success(f"location data being recieved from {d_detail.rider_id}: {location_data}")
    else:
        await _async_wa_client.send_message(
            to=d_detail.rider_id,
            text=f"I am unable to get your live location, please enable it by clicking the link sent to you.",
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

# %% Get live location on map 


# %% Dispatch and delivery complete
async def process_dispatch_complete(
    pool: AsyncConnectionPool,
    rider_id: str,
    callback_data: dict,
):
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            await cur.execute(
                """
                UPDATE delivery_dispatch
                SET status = 'completed'
                WHERE dispatch_id = %s
                """,
                (callback_data['dispatch_id'],),
            )
            await conn.commit()